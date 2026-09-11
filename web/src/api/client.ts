import type {
  ActionsResponse, ApiErrorBody, CatalogResponse, CommandResponse, CreateGameResponse,
  Language, ModuleId, ModulesResponse, RoomEvent, RoomResponse, Seat, ViewResponse, Viewer,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
    public readonly details: Record<string, unknown> = {},
  ) { super(message); }
}

export interface StoredSession {
  sessionId: string;
  revision: number;
  adminToken: string;
  seatTokens: Record<Seat, string>;
}

export interface StoredRoom {
  code: string;
  roomToken?: string;
  adminToken?: string;
  seat?: Seat;
  roomRevision: number;
  gameRevision: number;
}

export class ApiClient {
  private pending = new Map<string, AbortController>();

  constructor(public session: StoredSession | null = null, private baseUrl = "",
              public room: StoredRoom | null = null) {}

  private async request<T>(key: string, path: string, init: RequestInit = {}): Promise<T> {
    this.pending.get(key)?.abort();
    const controller = new AbortController();
    this.pending.set(key, controller);
    try {
      const response = await fetch(this.baseUrl + path, { ...init, signal: controller.signal });
      const data = await response.json() as T | ApiErrorBody;
      if (!response.ok) {
        const failure = data as ApiErrorBody;
        throw new ApiError(failure.error.code, failure.error.message, response.status,
                           failure.error.details);
      }
      return data as T;
    } finally {
      if (this.pending.get(key) === controller) this.pending.delete(key);
    }
  }

  private auth(token?: string): Record<string, string> {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  modules(language: Language = "zh") {
    return this.request<ModulesResponse>("modules", `/v1/modules?lang=${language}`);
  }

  catalog(module: ModuleId, language: Language = "zh") {
    return this.request<CatalogResponse>("catalog", `/v1/catalog/${module}?lang=${language}`);
  }

  async create(module: ModuleId): Promise<CreateGameResponse> {
    return this.acceptCreated(await this.request<CreateGameResponse>("game", "/v1/games", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module }),
    }));
  }

  async createFromSnapshot(snapshot: unknown): Promise<CreateGameResponse> {
    return this.acceptCreated(await this.request<CreateGameResponse>("game", "/v1/games", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snapshot }),
    }));
  }

  async createFromScenario(scenario: unknown): Promise<CreateGameResponse> {
    return this.acceptCreated(await this.request<CreateGameResponse>("game", "/v1/games", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario }),
    }));
  }

  private acceptCreated(created: CreateGameResponse): CreateGameResponse {
    this.session = {
      sessionId: created.session_id, revision: created.revision,
      adminToken: created.credentials.admin, seatTokens: created.credentials.seats,
    };
    return created;
  }

  async view(viewer: Viewer, language: Language = "zh"): Promise<ViewResponse> {
    if (this.room) {
      const response = await this.request<ViewResponse>("view",
        `/v1/rooms/${this.room.code}/game/view?lang=${language}`,
        { headers: this.auth(this.room.roomToken) });
      this.room.gameRevision = response.revision;
      return response;
    }
    const session = this.requireSession();
    const token = viewer === "spectator" ? undefined : session.seatTokens[viewer];
    const response = await this.request<ViewResponse>("view",
      `/v1/games/${session.sessionId}/view?viewer=${viewer}&lang=${language}`,
      { headers: this.auth(token) });
    session.revision = response.revision;
    return response;
  }

  async actions(actor: Seat): Promise<ActionsResponse> {
    if (this.room) {
      if (actor !== this.room.seat) throw new ApiError("FORBIDDEN", "只能读取自己的行动", 403);
      const response = await this.request<ActionsResponse>("actions",
        `/v1/rooms/${this.room.code}/game/actions`,
        { headers: this.auth(this.room.roomToken) });
      this.room.gameRevision = response.revision;
      return response;
    }
    const session = this.requireSession();
    const response = await this.request<ActionsResponse>("actions",
      `/v1/games/${session.sessionId}/actions?actor=${actor}`,
      { headers: this.auth(session.seatTokens[actor]) });
    session.revision = response.revision;
    return response;
  }

  async command(actor: Seat, actionId: string): Promise<CommandResponse> {
    if (this.room) {
      const response = await this.request<CommandResponse>("command",
        `/v1/rooms/${this.room.code}/game/commands`, {
          method: "POST",
          headers: { ...this.auth(this.room.roomToken), "Content-Type": "application/json" },
          body: JSON.stringify({ action_id: actionId, expected_revision: this.room.gameRevision }),
        });
      this.room.gameRevision = response.revision;
      return response;
    }
    const session = this.requireSession();
    const response = await this.request<CommandResponse>("command",
      `/v1/games/${session.sessionId}/commands`, {
        method: "POST",
        headers: { ...this.auth(session.seatTokens[actor]), "Content-Type": "application/json" },
        body: JSON.stringify({ action_id: actionId, expected_revision: session.revision }),
      });
    session.revision = response.revision;
    return response;
  }

  async snapshot(): Promise<unknown> {
    if (this.room) {
      const response = await this.request<{ snapshot: unknown }>("snapshot",
        `/v1/rooms/${this.room.code}/game/snapshot`,
        { headers: this.auth(this.room.adminToken) });
      return response.snapshot;
    }
    const session = this.requireSession();
    const response = await this.request<{ snapshot: unknown }>("snapshot",
      `/v1/games/${session.sessionId}/snapshot`,
      { headers: this.auth(session.adminToken) });
    return response.snapshot;
  }

  async replay(): Promise<string> {
    if (this.room) {
      const response = await fetch(`${this.baseUrl}/v1/rooms/${this.room.code}/game/replay`,
        { headers: this.auth(this.room.adminToken) });
      if (!response.ok) {
        const failure = await response.json() as ApiErrorBody;
        throw new ApiError(failure.error.code, failure.error.message, response.status,
                           failure.error.details);
      }
      return response.text();
    }
    const session = this.requireSession();
    const response = await fetch(`${this.baseUrl}/v1/games/${session.sessionId}/replay`,
      { headers: this.auth(session.adminToken) });
    if (!response.ok) {
      const failure = await response.json() as ApiErrorBody;
      throw new ApiError(failure.error.code, failure.error.message, response.status,
                         failure.error.details);
    }
    return response.text();
  }

  async createRoom(module: ModuleId, nickname: string, seat: Seat, spectators = true,
                   protagonistCount: 1 | 2 | 3 = 3) {
    const body: Record<string, unknown> = { module, nickname, seat, spectators };
    // Keep the original four-seat request wire-compatible with older hosts.
    // The server defaults an omitted value to three protagonist participants.
    if (protagonistCount !== 3) body.protagonist_count = protagonistCount;
    const response = await this.request<RoomResponse>("room-mutation", "/v1/rooms", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return this.acceptRoom(response);
  }

  async joinRoom(code: string, nickname: string, seat: Seat) {
    const response = await this.request<RoomResponse>("room-mutation", `/v1/rooms/${code}/join`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nickname, seat }),
    });
    return this.acceptRoom(response);
  }

  private acceptRoom(response: RoomResponse) {
    const credential = response.credential;
    if (!credential) throw new ApiError("INVALID_RESPONSE", "服务器没有返回房间凭据", 500);
    this.session = null;
    this.room = {
      code: response.room.code, roomToken: credential.room_token,
      adminToken: credential.admin_token, seat: credential.seat,
      roomRevision: response.room.revision, gameRevision: response.room.game_revision,
    };
    return response;
  }

  async roomStatus(code: string) {
    const token = this.room?.code === code ? this.room.roomToken : undefined;
    const response = await this.request<RoomResponse>("room-status", `/v1/rooms/${code}`,
      { headers: this.auth(token) });
    if (this.room?.code === code) {
      this.room.roomRevision = response.room.revision;
      this.room.gameRevision = response.room.game_revision;
    }
    return response;
  }

  observeRoom(response: RoomResponse) {
    if (!this.room || this.room.code !== response.room.code) {
      this.session = null;
      this.room = { code: response.room.code, roomRevision: response.room.revision,
                    gameRevision: response.room.game_revision };
    }
  }

  async roomUpdates() {
    const room = this.requireRoom();
    const response = await this.request<RoomResponse>("room-status",
      `/v1/rooms/${room.code}/updates?room_revision=${room.roomRevision}&game_revision=${room.gameRevision}`,
      { headers: this.auth(room.roomToken) });
    room.roomRevision = response.room.revision;
    return response;
  }

  async watchRoomEvents(signal: AbortSignal, onEvent: (event: RoomEvent) => void): Promise<void> {
    const room = this.requireRoom();
    const path = `/v1/rooms/${room.code}/events?room_revision=${room.roomRevision}&game_revision=${room.gameRevision}`;
    const response = await fetch(this.baseUrl + path, {
      headers: { ...this.auth(room.roomToken), Accept: "text/event-stream" }, signal,
    });
    if (!response.ok) {
      const failure = await response.json() as ApiErrorBody;
      throw new ApiError(failure.error.code, failure.error.message, response.status,
                         failure.error.details);
    }
    if (!response.body) throw new ApiError("STREAM_UNAVAILABLE", "浏览器无法读取房间事件流", 503);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        let eventType = "message";
        const data: string[] = [];
        for (const rawLine of block.split("\n")) {
          const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        }
        if (data.length) {
          const payload = JSON.parse(data.join("\n")) as RoomEvent | ApiErrorBody;
          if (eventType === "closed") {
            const failure = payload as ApiErrorBody;
            throw new ApiError(failure.error.code, failure.error.message, 404,
                               failure.error.details);
          }
          const update = payload as RoomEvent;
          if ((eventType === "revision" || eventType === "heartbeat")
              && Number.isInteger(update.room_revision) && Number.isInteger(update.game_revision)) {
            onEvent(update);
          }
        }
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
    }
    if (!signal.aborted) throw new ApiError("STREAM_CLOSED", "房间事件流已断开", 503);
  }

  async setReady(ready: boolean) {
    const room = this.requireRoom();
    return this.roomMutation("ready", { ready }, room.roomToken);
  }

  async startRoom() {
    const room = this.requireRoom();
    return this.roomMutation("start", undefined, room.adminToken);
  }

  async kickSeat(seat: Seat) {
    const room = this.requireRoom();
    return this.roomMutation("kick", { seat }, room.adminToken);
  }

  async setAiSeat(seat: Seat, enabled: boolean) {
    const room = this.requireRoom();
    return this.roomMutation("ai", { seat, enabled }, room.adminToken);
  }

  async leaveRoom() {
    const room = this.requireRoom();
    const response = await this.roomMutation("leave", undefined, room.roomToken);
    this.room = null;
    return response;
  }

  async closeRoom() {
    const room = this.requireRoom();
    const response = await this.request<{ deleted: boolean }>("room-mutation", `/v1/rooms/${room.code}`, {
      method: "DELETE", headers: this.auth(room.adminToken),
    });
    this.room = null;
    return response;
  }

  forgetRoom() {
    this.room = null;
    this.session = null;
  }

  private async roomMutation(action: string, body: unknown, token?: string) {
    const room = this.requireRoom();
    const init: RequestInit = { method: "POST", headers: this.auth(token) };
    if (body !== undefined) {
      init.headers = { ...init.headers, "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    const response = await this.request<RoomResponse>("room-mutation", `/v1/rooms/${room.code}/${action}`, init);
    room.roomRevision = response.room.revision;
    room.gameRevision = response.room.game_revision;
    return response;
  }

  private requireSession(): StoredSession {
    if (!this.session) throw new ApiError("NO_SESSION", "尚未创建对局", 400);
    return this.session;
  }

  private requireRoom(): StoredRoom {
    if (!this.room) throw new ApiError("NO_ROOM", "尚未加入房间", 400);
    return this.room;
  }
}
