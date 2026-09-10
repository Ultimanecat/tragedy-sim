import type {
  ActionsResponse, ApiErrorBody, CatalogResponse, CommandResponse, CreateGameResponse,
  Language, ModuleId, ModulesResponse, Seat, ViewResponse, Viewer,
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

export class ApiClient {
  private pending = new Map<string, AbortController>();

  constructor(public session: StoredSession | null = null, private baseUrl = "") {}

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
    const session = this.requireSession();
    const token = viewer === "spectator" ? undefined : session.seatTokens[viewer];
    const response = await this.request<ViewResponse>("view",
      `/v1/games/${session.sessionId}/view?viewer=${viewer}&lang=${language}`,
      { headers: this.auth(token) });
    session.revision = response.revision;
    return response;
  }

  async actions(actor: Seat): Promise<ActionsResponse> {
    const session = this.requireSession();
    const response = await this.request<ActionsResponse>("actions",
      `/v1/games/${session.sessionId}/actions?actor=${actor}`,
      { headers: this.auth(session.seatTokens[actor]) });
    session.revision = response.revision;
    return response;
  }

  async command(actor: Seat, actionId: string): Promise<CommandResponse> {
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
    const session = this.requireSession();
    const response = await this.request<{ snapshot: unknown }>("snapshot",
      `/v1/games/${session.sessionId}/snapshot`,
      { headers: this.auth(session.adminToken) });
    return response.snapshot;
  }

  async replay(): Promise<string> {
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

  private requireSession(): StoredSession {
    if (!this.session) throw new ApiError("NO_SESSION", "尚未创建对局", 400);
    return this.session;
  }
}
