/** Frozen JSON protocol v1. UI code must not infer rules from display text. */
export const PROTOCOL_VERSION = 1 as const;

export type Language = "zh" | "en" | "ja";
export type ModuleId = "FS" | "BTX" | "MZ" | "MC" | "HSA" | "WM" | "AHR" | "LL";
export type Seat = "m" | "a" | "b" | "c";
export type Viewer = Seat | "spectator";
export type LocationId = "hospital" | "shrine" | "city" | "school";
export type CounterId = "paranoia" | "goodwill" | "intrigue" | "hope" | "despair";
export type ActionType = "next" | "play" | "resolve" | "choose" | "guess" | "final";

export interface ApiErrorBody {
  protocol_version: typeof PROTOCOL_VERSION;
  error: { code: string; message: string; details: Record<string, unknown> };
}

export interface NamedItem { id: string; name: string }
export interface ModuleSummary extends NamedItem {
  cli_supported: boolean;
  gui_supported: boolean;
  final_guess: boolean;
  early_final_guess: boolean;
}
export interface ModulesResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  language: Language;
  modules: ModuleSummary[];
}

export interface AbilityDefinition {
  id: string;
  threshold: number;
  text: string;
  kind: string;
  scope: string;
  counter: CounterId;
  amount: number;
  once: boolean;
  unrefusable: boolean;
}
export interface CardDefinition extends NamedItem {
  effect: string;
  amount: number;
  once_per_loop: boolean;
}
export interface CatalogResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  language: Language;
  module: NamedItem & { subplot_count: number; capabilities: GameCapabilities };
  locations: NamedItem[];
  counters: NamedItem[];
  plots: Array<NamedItem & { type: "X" | "Y"; rule: string; roles: Record<string, number> }>;
  roles: Array<NamedItem & { rule: string }>;
  incidents: Array<NamedItem & { rule: string }>;
  characters: Array<NamedItem & {
    start: LocationId; limit: number; traits: NamedItem[];
    abilities: AbilityDefinition[]; forbidden: LocationId[]; passive: string;
  }>;
  cards: Record<Seat, CardDefinition[]>;
}

export interface CharacterView extends NamedItem {
  location: LocationId;
  forbidden: LocationId[];
  paranoia: number;
  goodwill: number;
  intrigue: number;
  hope: number;
  despair: number;
  alive: boolean;
  paranoia_limit: number;
  traits: string[];
  guard: number;
  abilities: AbilityDefinition[];
  passive: string;
  initial_location: LocationId;
  ex_cards: number;
  friended_token: boolean;
  death_token: boolean;
}
export interface PublicEvent {
  loop: number;
  round: number;
  phase: string;
  timing: string;
  timepoint: string;
  kind: string;
  message: string;
  [extra: string]: unknown;
}
export interface GameCapabilities { final_guess: boolean; early_final_guess: boolean }
export interface SecretView {
  roles: Record<string, string>;
  initial_roles: Record<string, string>;
  main_plot: string;
  subplots: string[];
  incidents: Array<Record<string, unknown>>;
  loss_reasons: string[];
  current_loop_days: number;
  ability_day_used: string[];
  ability_loop_used: string[];
  hidden_roles?: Record<string, string>;
  [extension: string]: unknown;
}
export interface GameView {
  module: ModuleId;
  module_name: string;
  title: string;
  language: Language;
  loop: number;
  loops: number;
  round: number;
  days: number;
  phase: string;
  phase_name: string;
  timing: string;
  timepoint: string;
  leader: Seat;
  controller: Seat | null;
  next_actor: Seat | null;
  winner: string | null;
  table_talk: boolean;
  action_counts: { mastermind: number; protagonists: number };
  protagonist_order: Seat[];
  characters: Record<string, CharacterView>;
  locations: Record<LocationId, number>;
  board_ex: Record<LocationId, number>;
  hand: string[];
  controlled_hands?: Partial<Record<Seat, string[]>>;
  participant?: {
    seat: Seat;
    human_leader: Seat;
    is_human_leader: boolean;
    card_actors: Seat[];
  };
  discarded: Record<Seat, string[]>;
  pending: Array<Record<string, unknown>>;
  events: PublicEvent[];
  labels: {
    actors: Record<Seat, string>;
    locations: Record<LocationId, string>;
    counters: Record<CounterId, string>;
  };
  capabilities: GameCapabilities;
  known_roles: Record<string, { role: string; loop: number; day: number }>;
  known_culprits: Record<string, string>;
  role_announcements: Array<Record<string, unknown>>;
  known_plots: string[];
  protected: boolean;
  ex_gauge: number;
  world: string | null;
  movement_locks: Record<string, number>;
  sealed_boards: Array<{ board: LocationId; through: number }>;
  ability_day_used: string[];
  ability_loop_used: string[];
  schedule: Array<{ day: number; kind: string }>;
  incidents: Array<Record<string, unknown>>;
  guess_remaining: string[];
  protagonist_secret?: "A" | "B" | "C";
  secret?: SecretView;
  [rulesetField: string]: unknown;
}

export interface ViewResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  session_id: string;
  revision: number;
  viewer: Viewer;
  state: GameView;
}
export interface Credentials { admin: string; seats: Record<Seat, string> }
export interface CreateGameResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  session_id: string;
  revision: number;
  credentials: Credentials;
  view: ViewResponse;
}
export interface ActionOffer {
  id: string;
  actor: Seat;
  type: ActionType | string;
  parameters: Record<string, string | number | boolean>;
  label: string;
  ui?: { source?: string };
}
export interface ActionsResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  session_id: string;
  revision: number;
  actor: Seat;
  controlled_actors?: Seat[];
  actions: ActionOffer[];
}
export interface CommandRequest { action_id: string; expected_revision: number }
export interface CommandResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  session_id: string;
  revision: number;
  accepted_action: ActionOffer;
  view: ViewResponse;
}

export interface RoomOccupant {
  nickname: string;
  ready: boolean;
  connected: boolean;
}
export interface RoomState {
  code: string;
  module: ModuleId;
  status: "waiting" | "playing" | "finished";
  revision: number;
  game_revision: number;
  spectators: boolean;
  protagonist_count: 1 | 2 | 3;
  required_seats: Seat[];
  human_leader: Seat;
  logical_leader: Seat;
  ready_to_start: boolean;
  seats: Record<Seat, RoomOccupant | null>;
}
export interface RoomCredential {
  room_token: string;
  admin_token?: string;
  seat: Seat;
}
export interface RoomResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  room: RoomState;
  self: { seat: Seat } | null;
  is_host: boolean;
  credential?: RoomCredential;
  room_changed?: boolean;
  game_changed?: boolean;
}
export interface RoomEvent {
  protocol_version: typeof PROTOCOL_VERSION;
  room_revision: number;
  game_revision: number;
}
