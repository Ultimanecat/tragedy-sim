import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, pointerWithin,
  useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent,
  type CollisionDetection,
} from "@dnd-kit/core";
import { ApiClient, ApiError, type StoredRoom, type StoredSession } from "./api/client";
import type { ActionOffer, CatalogResponse, GameView, ModuleId, ModuleSummary, PublicEvent, RoomResponse, Seat, Viewer } from "./api/types";
import { abilityUseName, itemName } from "./display";
import gameAssets from "./generated/game-assets.json";
import { parseReplayTimeline } from "./replay";

const SESSION_KEY = "tragedy-sim.local-session.v1";
const ROOM_KEY = "tragedy-sim.room.v1";
const seats: Viewer[] = ["spectator", "m", "a", "b", "c"];
const locations = ["hospital", "shrine", "city", "school"] as const;
const assetManifest = gameAssets as {
  characters: Record<string, string>;
  cards: Record<Seat, Record<string, string>>;
};

function assetUrl(kind: "characters", id: string): string | undefined;
function assetUrl(kind: "cards", seat: Seat, id: string): string | undefined;
function assetUrl(kind: "characters" | "cards", idOrSeat: string, card?: string) {
  const hash = kind === "characters"
    ? assetManifest.characters[idOrSeat]
    : assetManifest.cards[idOrSeat as Seat]?.[String(card)];
  return hash ? `/game-assets/${hash}.webp` : undefined;
}

function GameAsset({ src, className, draggable }: { src?: string; className?: string; draggable?: boolean }) {
  if (!src) return null;
  return <img className={className} src={src} alt="" loading="lazy" draggable={draggable}
    onError={event => { event.currentTarget.hidden = true; }} />;
}

export function AnimatedCounter({ label, value, suffix = "", hideWhenZero = false }: {
  label: string; value: number; suffix?: string; hideWhenZero?: boolean;
}) {
  const previous = useRef(value);
  const sequence = useRef(0);
  const [change, setChange] = useState<{ direction: "up" | "down"; sequence: number } | null>(null);
  const [visible, setVisible] = useState(!hideWhenZero || value !== 0);

  useEffect(() => {
    if (previous.current === value) {
      setVisible(!hideWhenZero || value !== 0);
      return;
    }
    const direction = value > previous.current ? "up" : "down";
    previous.current = value;
    sequence.current += 1;
    setVisible(true);
    setChange({ direction, sequence: sequence.current });
    const timer = window.setTimeout(() => {
      setChange(null);
      if (hideWhenZero && value === 0) setVisible(false);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [hideWhenZero, value]);

  if (!visible) return null;
  return <span key={change?.sequence ?? 0}
    className={`counter-token${change ? ` counter-${change.direction}` : ""}`}
    aria-label={`${label} ${value}${suffix}`}>
    {label} <strong>{value}</strong>{suffix}
  </span>;
}

function isMissingRoom(reason: unknown): boolean {
  return typeof reason === "object" && reason !== null && "code" in reason
    && (reason as { code?: unknown }).code === "ROOM_NOT_FOUND";
}

function loadSession(): StoredSession | null {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY) || "null") as StoredSession | null; }
  catch { return null; }
}

function loadRoom(code: string | null): StoredRoom | null {
  try {
    const stored = JSON.parse(localStorage.getItem(ROOM_KEY) || "null") as StoredRoom | null;
    return stored && stored.code === code ? stored : null;
  } catch { return null; }
}

function urlRoomCode() {
  const value = new URLSearchParams(window.location.search).get("room");
  return value?.trim() || null;
}

function download(name: string, contents: string, type: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; anchor.click();
  URL.revokeObjectURL(url);
}

function targetName(game: GameView, target: unknown) {
  const id = String(target ?? "");
  if (id.endsWith("@surface") || id.endsWith("@hidden")) {
    const [character, side] = id.split("@");
    return `${game.characters[character]?.name ?? character}（${side === "surface" ? "表" : "里"}身份）`;
  }
  return game.characters[id]?.name ?? game.labels.locations[id as keyof typeof game.locations] ?? id;
}

function winnerName(game: GameView) {
  if (game.winner === "protagonists") return "主人公胜利";
  if (game.winner === "mastermind") return "剧作家胜利";
  if (game.winner?.startsWith("traitor:")) {
    const seat = game.winner.slice(8) as Seat;
    return `背叛者（${game.labels.actors[seat]}）胜利`;
  }
  return game.winner ? `${game.winner}胜利` : "";
}

const smallestPointerTarget: CollisionDetection = args => pointerWithin(args).sort((left, right) => {
  const leftRect = args.droppableRects.get(left.id);
  const rightRect = args.droppableRects.get(right.id);
  return (leftRect ? leftRect.width * leftRect.height : Infinity)
    - (rightRect ? rightRect.width * rightRect.height : Infinity);
});

function BoardLocation({ id, offer, selected, density, children, onSelect }: {
  id: string; offer?: ActionOffer; selected: boolean; density: "normal" | "crowded" | "packed";
  children: React.ReactNode;
  onSelect?: (offer: ActionOffer) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({ id: `board:${id}`, data: { offer }, disabled: !offer });
  return <article ref={setNodeRef} className={`location location-${id} location-${density} ${offer ? "legal-board-target" : ""} ${selected ? "selected-board-target" : ""} ${isOver ? "drag-over" : ""}`}
    role={offer ? "button" : undefined} tabIndex={offer ? 0 : undefined}
    onClick={() => offer && onSelect?.(offer)}
    onKeyDown={event => { if (offer && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onSelect?.(offer); } }}>
    {children}
  </article>;
}

function BoardCharacter({ character, offer, selectedTarget, abilitySource, selectedSource, children, onTarget, onSource }: {
  character: GameView["characters"][string]; offer?: ActionOffer; selectedTarget: boolean;
  abilitySource: boolean; selectedSource: boolean; children: React.ReactNode;
  onTarget?: (offer: ActionOffer) => void; onSource?: (id: string) => void;
}) {
  const interactive = Boolean(offer || abilitySource);
  const { isOver, setNodeRef } = useDroppable({
    id: `board:${character.id}`, data: { offer }, disabled: !offer,
  });
  const activate = () => offer ? onTarget?.(offer) : abilitySource && onSource?.(character.id);
  return <div ref={setNodeRef}
    className={`character ${character.alive ? "" : "dead"} ${offer ? "legal-board-target" : ""} ${selectedTarget ? "selected-board-target" : ""} ${abilitySource ? "ability-source" : ""} ${selectedSource ? "selected-source" : ""} ${isOver ? "drag-over" : ""}`}
    role={interactive ? "button" : undefined} tabIndex={interactive ? 0 : undefined}
    onClick={event => {
      if ((event.target as Element).closest("[data-character-details]")) { event.stopPropagation(); return; }
      if (interactive) { event.stopPropagation(); activate(); }
    }}
    onKeyDown={event => {
      if ((event.target as Element).closest("[data-character-details]")) { event.stopPropagation(); return; }
      if (interactive && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); activate(); }
    }}>
    {children}
  </div>;
}

function CharacterDetailsDialog({ character, game, onClose }: {
  character: GameView["characters"][string]; game: GameView; onClose: () => void;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose]);
  return <div className="modal-backdrop" onClick={event => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="character-dialog" role="dialog" aria-modal="true"
      aria-labelledby={`character-dialog-${character.id}`}>
      <header><div><p className="eyebrow">CHARACTER</p><h2 id={`character-dialog-${character.id}`}>{character.name}</h2></div>
        <button autoFocus onClick={onClose}>关闭</button></header>
      <div className="character-dialog-body">
        <GameAsset className="character-dialog-art" src={assetUrl("characters", character.id)} />
        <div>
          <p><strong>{character.alive ? "存活" : "死亡"}</strong></p>
          <p>友好 {character.goodwill} · 不安 {character.paranoia}/{character.paranoia_limit} · 密谋 {character.intrigue}</p>
          {(character.hope > 0 || character.despair > 0 || character.guard > 0 || character.ex_cards > 0) && <p>
            {[
              character.hope > 0 ? `希望 ${character.hope}` : "",
              character.despair > 0 ? `绝望 ${character.despair}` : "",
              character.guard > 0 ? `护卫 ${character.guard}` : "",
              character.ex_cards > 0 ? `${game.module === "HSA" ? "诅咒" : "Ex"} ${character.ex_cards}` : "",
            ].filter(Boolean).join(" · ")}
          </p>}
          <p>属性：{character.traits.join("、") || "无"}</p>
          <p>禁行：{character.forbidden.map(id => game.labels.locations[id]).join("、") || "无"}</p>
        </div>
      </div>
      <div className="character-dialog-rules">
        {character.abilities.length ? character.abilities.map(ability => <p key={`${ability.id}-${ability.threshold}`}>
          <strong>友好 {ability.threshold}</strong>：{ability.text}{ability.once ? "（限次）" : ""}{ability.unrefusable ? "（不可拒绝）" : ""}
        </p>) : <p className="muted">没有角色固有能力。</p>}
        {character.passive && <p><strong>被动</strong>：{character.passive}</p>}
      </div>
    </section>
  </div>;
}

export function Board({ game, catalog, targetOffers = [], selectedOffer, abilitySources = [], selectedSource,
  onTarget, onSource }: {
  game: GameView; catalog: CatalogResponse | null; targetOffers?: ActionOffer[]; selectedOffer?: ActionOffer | null;
  abilitySources?: string[]; selectedSource?: string | null;
  onTarget?: (offer: ActionOffer) => void; onSource?: (id: string) => void;
}) {
  const cardName = (actor: string, id: unknown) => id
    ? itemName(catalog?.cards[actor as Seat], id) : "暗牌";
  const [detailsCharacter, setDetailsCharacter] = useState<string | null>(null);
  const boardCounter = game.module === "HSA" ? "尸体" : "密谋";
  const offerByTarget = new Map(targetOffers.map(offer => [String(offer.parameters.target), offer]));
  return <>
    <section className="board" aria-label="游戏版图">
      {locations.map(location => {
        const characters = Object.values(game.characters).filter(character => character.location === location);
        const density = characters.length >= 9 ? "packed" : characters.length >= 5 ? "crowded" : "normal";
        return <BoardLocation id={location} offer={offerByTarget.get(location)} density={density}
          selected={selectedOffer?.parameters.target === location} onSelect={onTarget} key={location}>
          <header><h2>{game.labels.locations[location]}</h2><div className="location-summary">
            <AnimatedCounter label={boardCounter} value={game.locations[location]} />
            <AnimatedCounter label="诅咒" value={game.board_ex[location]} hideWhenZero />
            <span>{characters.length} 人</span>
          </div></header>
          <div className="characters">
          {characters.map(character =>
            <BoardCharacter character={character} offer={offerByTarget.get(character.id)}
              selectedTarget={selectedOffer?.parameters.target === character.id}
              abilitySource={abilitySources.includes(character.id)} selectedSource={selectedSource === character.id}
              onTarget={onTarget} onSource={onSource} key={character.id}>
              <GameAsset className="character-art" src={assetUrl("characters", character.id)} />
              <div className="character-body">
                <div className="character-title"><strong>{character.name}</strong><small>{character.alive ? "存活" : "死亡"}</small></div>
                <div className="counters">
                  <AnimatedCounter label="友好" value={character.goodwill} />
                  <AnimatedCounter label="不安" value={character.paranoia} suffix={`/${character.paranoia_limit}`} />
                  <AnimatedCounter label="密谋" value={character.intrigue} />
                  <AnimatedCounter label="希望" value={character.hope} hideWhenZero />
                  <AnimatedCounter label="绝望" value={character.despair} hideWhenZero />
                  <AnimatedCounter label="护卫" value={character.guard} hideWhenZero />
                  <AnimatedCounter label={game.module === "HSA" ? "诅咒" : "Ex"} value={character.ex_cards} hideWhenZero />
                  {character.friended_token && <span className="counter-token counter-flag">交友完毕</span>}
                  {character.death_token && <span className="counter-token counter-flag">死亡完毕</span>}
                </div>
                <button type="button" className="character-reference-button" data-character-details
                  aria-label={`查看${character.name}资料`} onClick={() => setDetailsCharacter(character.id)}>查看资料</button>
              </div>
            </BoardCharacter>)}
          </div>
        </BoardLocation>;
      })}
    </section>
    {detailsCharacter && game.characters[detailsCharacter] && <CharacterDetailsDialog
      character={game.characters[detailsCharacter]} game={game} onClose={() => setDetailsCharacter(null)} />}
    {(["MC", "WM", "AHR"].includes(game.module) || game.world || game.sealed_boards.length > 0 || Object.keys(game.movement_locks).length > 0) &&
      <section className="panel public-effects"><h2>公开特殊状态</h2>
        {["MC", "WM", "AHR"].includes(game.module) && <span>Ex 槽 {game.ex_gauge}</span>}
        {game.world && <span>当前世界：{game.world === "surface" ? "表世界" : "里世界"}</span>}
        {game.sealed_boards.map(item => <span key={item.board}>{game.labels.locations[item.board]}封锁至第 {item.through} 天</span>)}
        {Object.entries(game.movement_locks).map(([id, day]) => <span key={id}>{game.characters[id]?.name ?? id}第 {day} 天不能移动</span>)}
      </section>}
    {!!game.pending.length && <section className="panel placements"><h2>本日已放置</h2>
      {game.pending.map((placement, index) => <span className="placement" key={`${String(placement.actor)}-${index}`}>
        {game.labels.actors[placement.actor as Seat]} → {targetName(game, placement.target)}：{cardName(String(placement.actor), placement.card)}
      </span>)}
    </section>}
  </>;
}

function Cards({ game, catalog, viewer }: { game: GameView; catalog: CatalogResponse | null; viewer: Viewer }) {
  const cardName = (seat: Seat, id: string) => itemName(catalog?.cards[seat], id);
  const discarded = Object.entries(game.discarded).filter(([, cards]) => cards.length);
  const hands = game.controlled_hands ?? (viewer === "spectator" ? {} : { [viewer]: game.hand });
  return <section className="panel"><h2>手牌与公开留置</h2>
    {Object.entries(hands).map(([seat, cards]) => <div key={seat}><h3>{game.labels.actors[seat as Seat]}手牌
      {game.participant?.card_actors.includes(seat as Seat) && seat !== game.participant.seat ? "（由你代管）" : ""}</h3>
      <div className="card-list">{cards?.map(id => <span key={id}>
        <GameAsset src={assetUrl("cards", seat as Seat, id)} />{cardName(seat as Seat, id)}
      </span>)}</div></div>)}
    {!discarded.length && <p className="muted">目前没有公开留置牌。</p>}
    {discarded.map(([seat, cards]) => <p key={seat}>{game.labels.actors[seat as Seat]}：
      {cards.map(id => cardName(seat as Seat, id)).join("、")}</p>)}
  </section>;
}

function DraggableActionCard({ id, name, imageUrl, selected, busy, onSelect }: {
  id: string; name: string; imageUrl?: string; selected: boolean; busy: boolean; onSelect: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `card:${id}`, data: { card: id }, disabled: busy,
  });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  return <button ref={setNodeRef} style={style}
    className={`${selected ? "selected" : ""} ${isDragging ? "dragging" : ""}`}
    disabled={busy} onClick={onSelect} {...listeners} {...attributes}>
    <GameAsset src={imageUrl} draggable={false} />
    <span><strong>{name}</strong></span>
  </button>;
}

export function Actions({ offers, catalog, game, busy, onAction }: {
  offers: ActionOffer[]; catalog: CatalogResponse | null; game: GameView;
  busy: boolean; onAction: (offer: ActionOffer) => void;
}) {
  const [selectedCard, setSelectedCard] = useState<string | null>(null);
  const [selectedGuess, setSelectedGuess] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [selected, setSelected] = useState<ActionOffer | null>(null);
  const [draggedCard, setDraggedCard] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  );
  const playGroups = useMemo(() => {
    const groups = new Map<string, ActionOffer[]>();
    for (const item of offers.filter(candidate => candidate.type === "play")) {
      const key = String(item.parameters.card);
      groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    return groups;
  }, [offers]);
  const guessGroups = useMemo(() => {
    const groups = new Map<string, ActionOffer[]>();
    for (const item of offers.filter(candidate => candidate.type === "guess")) {
      const key = String(item.parameters.character);
      groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    return groups;
  }, [offers]);
  const others = offers.filter(item => item.type !== "play" && item.type !== "guess");
  const sourcedActions = others.filter(item => item.ui?.source && game.characters[item.ui.source]);
  const unsourcedActions = others.filter(item => !item.ui?.source || !game.characters[item.ui.source]);
  const sourceCharacters = [...new Set(sourcedActions.map(item => String(item.ui?.source)))];
  const selectedSourceActions = sourcedActions.filter(item => item.ui?.source === selectedSource);
  const actor = offers[0]?.actor;
  const choices = selectedCard ? playGroups.get(selectedCard) ?? [] : [];
  const guesses = selectedGuess ? guessGroups.get(selectedGuess) ?? [] : [];
  const startDrag = (event: DragStartEvent) => {
    const card = String(event.active.data.current?.card ?? "");
    if (!playGroups.has(card)) return;
    setDraggedCard(card); setSelectedCard(card); setSelected(null);
  };
  const finishDrag = (event: DragEndEvent) => {
    setDraggedCard(null);
    const offer = event.over?.data.current?.offer as ActionOffer | undefined;
    // dnd-kit briefly suppresses the click following a pointer drag. Publishing
    // the confirmation after that guard is removed prevents the first tap on the
    // confirmation button from being swallowed on touch devices.
    if (offer && choices.some(choice => choice.id === offer.id)) {
      window.setTimeout(() => setSelected(offer), 80);
    }
  };
  return <DndContext sensors={sensors} collisionDetection={smallestPointerTarget}
    onDragStart={startDrag} onDragEnd={finishDrag} onDragCancel={() => setDraggedCard(null)}>
    <Board game={game} catalog={catalog} targetOffers={choices} selectedOffer={selected}
      abilitySources={sourceCharacters} selectedSource={selectedSource}
      onTarget={offer => setSelected(offer)} onSource={source => { setSelectedSource(source); setSelected(null); }} />
    <section className={`panel actions-panel ${offers.length ? "has-actions" : "is-waiting"}`}>
    <header className="action-header"><div><p className="eyebrow">TURN ACTION</p><h2>可执行行动</h2></div>
      {actor && <span className="actor-badge">{game.labels.actors[actor as Seat]}</span>}</header>
    {!offers.length && <p className="muted">当前视角没有可执行行动。</p>}
    {!!unsourcedActions.length && <div className="action-grid">{unsourcedActions.map(offer =>
      <button className={selected?.id === offer.id ? "selected" : ""} disabled={busy} key={offer.id}
        onClick={() => setSelected(offer)}>{offer.label}</button>)}</div>}
    {!!sourcedActions.length && <><p className="step-label">先在上方版图选择发动力量的角色</p>
      {selectedSource && <div className="action-grid ability-actions">{selectedSourceActions.map(offer =>
        <button className={selected?.id === offer.id ? "selected" : ""} disabled={busy} key={offer.id}
          onClick={() => setSelected(offer)}>{offer.label}</button>)}</div>}</>}
    {!!playGroups.size && <>
      <p className="step-label">选择手牌，然后点击或拖到上方发亮的角色／版图</p><div className="hand">
        {[...playGroups].map(([card]) => <DraggableActionCard key={card} id={card}
          name={itemName(actor ? catalog?.cards[actor] : undefined, card)}
          imageUrl={actor ? assetUrl("cards", actor as Seat, card) : undefined}
          selected={selectedCard === card} busy={busy}
          onSelect={() => { setSelectedCard(card); setSelected(null); }} />)}
      </div>
    </>}
    {!!guessGroups.size && <>
      <p className="step-label">1. 选择要猜测的角色/身份面</p><div className="guess-characters">
        {[...guessGroups].map(([character, available]) => <button className={selectedGuess === character ? "selected" : ""}
          disabled={busy} key={character} onClick={() => { setSelectedGuess(character); setSelected(null); }}>
          {targetName(game, character)}<small>{available.length} 个身份候选</small>
        </button>)}
      </div>
      {selectedGuess && <><p className="step-label">2. 选择身份</p><div className="action-grid">
        {guesses.map(offer => <button className={selected?.id === offer.id ? "selected" : ""}
          disabled={busy} key={offer.id} onClick={() => setSelected(offer)}>
          {itemName(catalog?.roles, offer.parameters.role)}</button>)}
      </div></>}
    </>}
    {selected && <div className="confirm-bar"><span>{selected.label}</span>
      <button className="primary" disabled={busy} onClick={() => onAction(selected)}>确认执行</button></div>}
    </section>
    <DragOverlay dropAnimation={null}>{draggedCard ? <div className="drag-card-overlay">
      {actor && <GameAsset src={assetUrl("cards", actor as Seat, draggedCard)} />}
      <span>{itemName(actor ? catalog?.cards[actor] : undefined, draggedCard)}</span></div> : null}</DragOverlay>
  </DndContext>;
}

function Knowledge({ game, catalog }: { game: GameView; catalog: CatalogResponse | null }) {
  const roles = Object.entries(game.known_roles);
  const culprits = Object.entries(game.known_culprits);
  return <section className="panel"><h2>公开知识</h2>
    {!roles.length && !culprits.length && !game.known_plots.length &&
      !game.ability_day_used.length && !game.ability_loop_used.length && !game.protected && <p className="muted">尚无额外公开情报。</p>}
    {roles.map(([character, fact]) => {
      const claim = [...game.role_announcements].reverse().find(item => item.character === character);
      return <p key={character}>{game.module === "MZ" ? "公开宣称" : "历史确认"}：{game.characters[character]?.name ?? character} →
        {itemName(catalog?.roles, fact.role)}（轮回 {fact.loop} / 第 {fact.day} 天）
        {claim?.may_be_ninja_claim ? "（可能是忍者的宣称）" : ""}</p>;
    })}
    {culprits.map(([day, character]) => <p key={day}>第 {day} 天事件当事人：{game.characters[character]?.name ?? character}</p>)}
    {game.known_plots.map(plot => <p key={plot}>已公开规则：{itemName(catalog?.plots, plot)}</p>)}
    {[...new Set([...game.ability_day_used, ...game.ability_loop_used])].map(key => <p key={key}>
      已声明能力：{abilityUseName(game, key, catalog)}{game.ability_loop_used.includes(key) ? "（本轮限次已使用）" : "（今日已使用）"}</p>)}
    {game.protected && <p>本轮主人公受到公开保护。</p>}
    {game.phase === "final_guess" && <p>最终猜测尚余：{game.guess_remaining.map(id => targetName(game, id)).join("、") || "无"}</p>}
  </section>;
}

function RulesReference({ catalog }: { catalog: CatalogResponse | null }) {
  if (!catalog) return null;
  return <section className="panel reference"><h2>规则速查</h2>
    <details><summary>事件（{catalog.incidents.length}）</summary>{catalog.incidents.map(item => <p key={item.id}><strong>{item.name}</strong>：{item.rule}</p>)}</details>
    <details><summary>身份（{catalog.roles.length}）</summary>{catalog.roles.map(item => <p key={item.id}><strong>{item.name}</strong>：{item.rule}</p>)}</details>
    <details><summary>规则候选（{catalog.plots.length}）</summary>{catalog.plots.map(item => <p key={item.id}><strong>{item.type} · {item.name}</strong>：{item.rule}</p>)}</details>
  </section>;
}

function PublicLog({ game, catalog }: { game: GameView; catalog: CatalogResponse | null }) {
  const [scope, setScope] = useState<"today" | "loop" | "all">("today");
  const [query, setQuery] = useState("");
  const normalized = query.trim().toLocaleLowerCase();
  const visible = game.events.filter(event => {
    if (scope === "today" && (event.loop !== game.loop || event.round !== game.round)) return false;
    if (scope === "loop" && event.loop !== game.loop) return false;
    return !normalized || `${event.timepoint} ${event.message}`.toLocaleLowerCase().includes(normalized);
  });
  const groups = new Map<string, PublicEvent[]>();
  for (const event of visible) {
    const key = `${event.loop}:${event.round}:${event.timepoint}`;
    groups.set(key, [...(groups.get(key) ?? []), event]);
  }
  return <section className="panel log"><header className="log-header"><h2>公开日志</h2>
    <select aria-label="日志范围" value={scope} onChange={event => setScope(event.target.value as typeof scope)}>
      <option value="today">今日</option><option value="loop">本轮回</option><option value="all">全部</option>
    </select></header>
    <input className="log-search" aria-label="搜索公开日志" value={query}
      onChange={event => setQuery(event.target.value)} placeholder="搜索时间点或内容" />
    {!visible.length && <p className="muted">此范围内没有匹配记录。</p>}
    {[...groups.entries()].reverse().map(([key, events]) => <section className="log-group" key={key}>
      <h3>{events[0].timepoint}</h3>{[...events].reverse().map((event, index) =>
        <article key={`${event.kind}-${index}`}><p>{event.message}</p>
          {Array.isArray(event.cards) && event.cards.map((placement, cardIndex) => {
            const card = placement as Record<string, unknown>;
            const actor = String(card.actor) as Seat;
            return <p className="log-detail" key={cardIndex}>{game.labels.actors[actor]}：
              {itemName(catalog?.cards[actor], card.card)} → {targetName(game, card.target)}</p>;
          })}</article>)}
    </section>)}
  </section>;
}

function ReplayDialog({ text, onClose }: { text: string; onClose: () => void }) {
  const entries = useMemo(() => parseReplayTimeline(text), [text]);
  const [position, setPosition] = useState(() => Math.max(0, entries.length - 1));
  const current = entries[position];
  return <section className="replay" role="dialog" aria-modal="true" aria-label="只读回放">
    <header><div><p className="eyebrow">FULL INFORMATION REPLAY</p><h2>对局回放</h2></div><button onClick={onClose}>关闭</button></header>
    {!entries.length ? <pre>{text}</pre> : <div className="replay-workspace">
      <nav className="replay-timeline" aria-label="回放决策时间轴">{entries.map((entry, index) =>
        <button className={index === position ? "selected" : ""} key={entry.number} onClick={() => setPosition(index)}>
          <small>#{String(entry.number).padStart(4, "0")} · {entry.timepoint}</small><span>{entry.description}</span>
        </button>)}</nav>
      <article className="replay-detail"><small>决策 {position + 1}/{entries.length}</small>
        <h3>{current.timepoint} · {current.phase}</h3><p className="replay-decision">{current.description}</p>
        <h4>结算记录</h4>{current.steps.length ? current.steps.map((step, index) =>
          <p className="replay-step" key={index}><small>{step.timepoint}</small>{step.message}</p>)
          : <p className="muted">这个决策没有产生额外的公开结算记录。</p>}
        <div className="replay-controls"><button disabled={position === 0} onClick={() => setPosition(value => value - 1)}>上一步</button>
          <input aria-label="回放位置" type="range" min="0" max={entries.length - 1} value={position}
            onChange={event => setPosition(Number(event.target.value))} />
          <button disabled={position === entries.length - 1} onClick={() => setPosition(value => value + 1)}>下一步</button></div>
        <details><summary>查看原始纯文本</summary><pre>{text}</pre></details>
      </article>
    </div>}
  </section>;
}

export default function App() {
  const [initialRoom] = useState(urlRoomCode);
  const [client] = useState(() => new ApiClient(loadSession(), "", loadRoom(initialRoom)));
  const [modules, setModules] = useState<ModuleSummary[]>([]);
  const [module, setModule] = useState<ModuleId>("BTX");
  const [viewer, setViewer] = useState<Viewer>(client.room?.seat ?? "spectator");
  const [roomCode, setRoomCode] = useState<string | null>(initialRoom);
  const [roomInfo, setRoomInfo] = useState<RoomResponse | null>(null);
  const [nickname, setNickname] = useState("");
  const [preferredSeat, setPreferredSeat] = useState<Seat>("m");
  const [roomEntry, setRoomEntry] = useState("");
  const [allowSpectators, setAllowSpectators] = useState(true);
  const [protagonistCount, setProtagonistCount] = useState<1 | 2 | 3>(3);
  const [game, setGame] = useState<GameView | null>(null);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [offers, setOffers] = useState<ActionOffer[]>([]);
  const [replayText, setReplayText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [roomUnavailable, setRoomUnavailable] = useState(false);
  const effectiveProtagonistCount: 1 | 2 | 3 = module === "LL" ? 3 : protagonistCount;

  const persist = useCallback(() => {
    if (client.session) localStorage.setItem(SESSION_KEY, JSON.stringify(client.session));
    if (client.room) localStorage.setItem(ROOM_KEY, JSON.stringify(client.room));
    else localStorage.removeItem(ROOM_KEY);
  }, [client]);

  const refresh = useCallback(async (nextViewer = viewer, quiet = false) => {
    if (!client.session && !client.room) return;
    if (!quiet) { setBusy(true); setError(""); }
    try {
      const response = await client.view(nextViewer);
      setGame(response.state);
      const actor = response.state.controller;
      const ownSeat = client.room?.seat;
      if (client.room && ownSeat) setOffers((await client.actions(ownSeat)).actions);
      else setOffers(actor && actor === nextViewer ? (await client.actions(actor)).actions : []);
      persist();
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (isMissingRoom(reason)) setRoomUnavailable(true);
      setError(reason instanceof Error ? reason.message : "读取对局失败");
    } finally { if (!quiet) setBusy(false); }
  }, [client, persist, viewer]);

  useEffect(() => { client.modules().then(result => setModules(result.modules)).catch(() => setError("无法读取规则集目录")); }, [client]);
  useEffect(() => {
    if (!client.session || roomCode) return;
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [client, refresh, roomCode]);
  useEffect(() => {
    if (!roomCode) return;
    let active = true;
    let syncing = false;
    let syncPending = false;
    let failures = 0;
    let fallbackTimer: number | undefined;
    let reconnectTimer: number | undefined;
    let streamController: AbortController | undefined;
    const stopFallback = () => {
      if (fallbackTimer !== undefined) window.clearInterval(fallbackTimer);
      fallbackTimer = undefined;
    };
    const sync = async (initial = false) => {
      if (!active) return;
      if (syncing) { syncPending = true; return; }
      syncing = true;
      try {
        const response = initial || !client.room
          ? await client.roomStatus(roomCode) : await client.roomUpdates();
        if (!client.room) client.observeRoom(response);
        if (!active) return;
        setRoomUnavailable(false);
        // Avoid replacing the lobby tree on every no-op poll (which can interrupt
        // typing on slower/mobile browsers), but retain meaningful presence changes.
        setRoomInfo(current => {
          const presenceChanged = current && response.room.required_seats.some(seat =>
            current.room.seats[seat]?.connected !== response.room.seats[seat]?.connected);
          return initial || response.room_changed || response.game_changed || presenceChanged || !current
            ? response : current;
        });
        setModule(response.room.module);
        const seat = client.room?.seat ?? "spectator";
        setViewer(seat);
        persist();
        if (response.room.status !== "waiting" && (initial || response.game_changed || response.room_changed)) {
          await refresh(seat, true);
        }
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (active) {
          if (isMissingRoom(reason)) setRoomUnavailable(true);
          setError(reason instanceof Error ? reason.message : "读取房间失败");
        }
      } finally {
        syncing = false;
        if (syncPending && active) { syncPending = false; void sync(); }
      }
    };
    const startFallback = () => {
      if (fallbackTimer === undefined) fallbackTimer = window.setInterval(() => void sync(), 3_000);
      void sync();
    };
    const connect = async () => {
      if (!active || !client.room) { startFallback(); return; }
      streamController = new AbortController();
      try {
        await client.watchRoomEvents(streamController.signal, () => {
          failures = 0;
          stopFallback();
          void sync();
        });
      } catch (reason) {
        if (!active || (reason instanceof DOMException && reason.name === "AbortError")) return;
        if (isMissingRoom(reason)) {
          setRoomUnavailable(true);
          setError(reason instanceof Error ? reason.message : "房间不存在或已经关闭");
          return;
        }
        startFallback();
        const delay = Math.min(1_000 * (2 ** failures), 15_000);
        failures += 1;
        reconnectTimer = window.setTimeout(() => void connect(), delay);
      }
    };
    void (async () => { await sync(true); if (active) void connect(); })();
    return () => {
      active = false;
      streamController?.abort();
      stopFallback();
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
    };
  }, [client, persist, refresh, roomCode]);
  useEffect(() => {
    if (!game?.module) return;
    client.catalog(game.module).then(setCatalog).catch(() => setError("无法读取规则资料"));
  }, [client, game?.module]);
  async function createGame() {
    setBusy(true); setError(""); setOffers([]); setCatalog(null); setReplayText(""); setViewer("spectator");
    try { await client.create(module); persist(); await refresh("spectator"); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "创建对局失败"); }
    finally { setBusy(false); }
  }

  function enterRoom(code: string) {
    const normalized = code.trim();
    setRoomUnavailable(false); setError("");
    setRoomCode(normalized);
    window.history.replaceState(null, "", `${window.location.pathname}?room=${normalized}`);
  }

  async function createRoom() {
    setBusy(true); setError("");
    try {
      const response = await client.createRoom(module, nickname, preferredSeat, allowSpectators, effectiveProtagonistCount);
      setRoomInfo(response); setViewer(preferredSeat); persist(); enterRoom(response.room.code);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "创建房间失败"); }
    finally { setBusy(false); }
  }

  async function joinRoom(seat: Seat) {
    if (!roomCode) return;
    setBusy(true); setError("");
    try {
      const response = await client.joinRoom(roomCode, nickname, seat);
      setRoomInfo(response); setViewer(seat); persist();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "加入房间失败"); }
    finally { setBusy(false); }
  }

  async function setRoomReady(ready: boolean) {
    setBusy(true); setError("");
    try { const response = await client.setReady(ready); setRoomInfo(response); persist(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "准备状态更新失败"); }
    finally { setBusy(false); }
  }

  async function startRoom() {
    setBusy(true); setError("");
    try {
      const response = await client.startRoom(); setRoomInfo(response); persist();
      await refresh(client.room?.seat ?? "spectator");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "开始房间失败"); }
    finally { setBusy(false); }
  }

  async function kickRoomSeat(seat: Seat) {
    try { setRoomInfo(await client.kickSeat(seat)); persist(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "释放座位失败"); }
  }

  async function setAiRoomSeat(seat: Seat, enabled: boolean,
                               strategy: "random" | "fixed_mastermind" = "random") {
    setBusy(true); setError("");
    try { setRoomInfo(await client.setAiSeat(seat, enabled, strategy)); persist(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "AI 座位更新失败"); }
    finally { setBusy(false); }
  }

  async function leaveOrCloseRoom() {
    setBusy(true); setError("");
    try {
      if (client.room?.adminToken) await client.closeRoom(); else await client.leaveRoom();
      localStorage.removeItem(ROOM_KEY); setRoomCode(null); setRoomInfo(null); setGame(null); setOffers([]);
      window.history.replaceState(null, "", window.location.pathname);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "离开房间失败"); }
    finally { setBusy(false); }
  }

  function returnToLobby() {
    client.forgetRoom();
    localStorage.removeItem(ROOM_KEY);
    setRoomCode(null); setRoomInfo(null); setGame(null); setOffers([]); setReplayText("");
    setRoomUnavailable(false); setError("");
    window.history.replaceState(null, "", window.location.pathname);
  }

  function switchViewer(next: Viewer) {
    if (next === viewer) return;
    setViewer(next); setGame(null); setOffers([]); setReplayText(""); setError("");
  }

  async function act(offer: ActionOffer) {
    setBusy(true); setError(""); setOffers([]);
    try { await client.command(offer.actor as Seat, offer.id); persist(); await refresh(viewer); }
    catch (reason) {
      if (reason instanceof ApiError && reason.code === "STALE_REVISION") await refresh(viewer);
      setError(reason instanceof Error ? reason.message : "行动提交失败");
    } finally { setBusy(false); }
  }

  async function saveSnapshot() {
    try { download("tragedy-sim-save.json", JSON.stringify(await client.snapshot(), null, 2), "application/json"); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); }
  }

  async function readReplay(shouldDownload = false) {
    try {
      const text = await client.replay(); setReplayText(text);
      if (shouldDownload) download("tragedy-sim-replay.tlr", text, "text/plain;charset=utf-8");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "对局结束后才能查看回放"); }
  }

  async function restore(file: File) {
    setBusy(true); setError(""); setOffers([]); setCatalog(null); setReplayText(""); setViewer("spectator");
    try {
      const data = JSON.parse(await file.text()) as Record<string, unknown>;
      if (data.version === 1 && Array.isArray(data.commands)) await client.createFromSnapshot(data);
      else await client.createFromScenario(data);
      persist(); await refresh("spectator");
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "存档无效"); }
    finally { setBusy(false); }
  }

  const ownSeat = client.room?.seat;
  const ownOccupant = ownSeat ? roomInfo?.room.seats[ownSeat] : null;
  const roomReady = roomInfo?.room.ready_to_start ?? false;
  const shareUrl = roomCode ? `${window.location.origin}${window.location.pathname}?room=${roomCode}` : "";

  return <main>
    <header className="masthead"><div><p className="eyebrow">TRAGEDY LOOPER</p><h1>悲剧轮回</h1></div>{roomCode ? <div className="room-heading">
      <small>局域网房间</small><strong>{roomCode}</strong>
    </div> : <div className="new-game">
      <select aria-label="规则集" value={module} onChange={event => setModule(event.target.value as ModuleId)}>
        {modules.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
      <button className="primary" disabled={busy} onClick={createGame}>新建对局</button>
      <label className="file-button">载入存档/剧本<input type="file" accept="application/json" onChange={event => event.target.files?.[0] && void restore(event.target.files[0])} /></label>
    </div>}</header>
    {error && <div className="error" role="alert">{error}</div>}
    {roomCode && roomUnavailable ? <section className="empty room-unavailable"><h2>无法进入房间</h2>
      <p>该房间不存在、已经关闭，或服务重启后房间记录已经清空。</p>
      <button className="primary" onClick={returnToLobby}>返回大厅</button>
    </section> : roomCode && (!roomInfo || roomInfo.room.status === "waiting") ? <section className="lobby" aria-label="房间大厅">
      {!roomInfo ? <h2>正在连接房间 {roomCode}…</h2> : <>
        <div className="lobby-intro"><div><p className="eyebrow">WAITING ROOM</p><h2>等待所有玩家入座并准备</h2></div>
          <div><label>邀请链接<input readOnly value={shareUrl} onFocus={event => event.currentTarget.select()} /></label><small>复制此链接给同一 Wi-Fi 下的玩家。</small></div></div>
        <p className="muted">本局由 1 名剧作家和 {roomInfo.room.protagonist_count} 名主人公玩家参与。</p>
        <div className="seat-grid">{roomInfo.room.required_seats.map(seat => {
          const occupant = roomInfo.room.seats[seat];
          return <article className={`${occupant ? "occupied" : ""} ${occupant?.ai ? "ai-seat" : ""}`} key={seat}>
            <small>{seat === "m" ? "剧作家" : `主人公 ${seat.toUpperCase()}`}</small>
            <strong>{occupant?.nickname ?? "空位"}{occupant?.ai && <small className="ai-badge">AI</small>}</strong>
            <span>{occupant?.ai ? (occupant.ai_type === "fixed_mastermind" ? "从可行获胜定式中择一执行" : "自动随机行动") : occupant ? (occupant.ready ? "已准备" : "尚未准备") : "等待加入"}</span>
            {!ownSeat && !occupant && <button disabled={busy || !nickname.trim()} onClick={() => void joinRoom(seat)}>坐到这里</button>}
            {client.room?.adminToken && !occupant && <button disabled={busy} onClick={() => void setAiRoomSeat(seat, true)}>随机 AI</button>}
            {client.room?.adminToken && !occupant && seat === "m" && <button disabled={busy}
              onClick={() => void setAiRoomSeat(seat, true, "fixed_mastermind")}>定式剧作家 AI</button>}
            {client.room?.adminToken && occupant && seat !== ownSeat && <button disabled={busy}
              onClick={() => void (occupant.ai ? setAiRoomSeat(seat, false) : kickRoomSeat(seat))}>释放座位</button>}
          </article>;
        })}</div>
        {!ownSeat ? <div className="lobby-controls"><label>你的昵称<input maxLength={24} value={nickname} onChange={event => setNickname(event.target.value)} placeholder="先输入昵称，再选择座位" /></label></div>
          : <div className="lobby-controls"><strong>你是：{ownSeat === "m" ? "剧作家" : `主人公 ${ownSeat.toUpperCase()}`}</strong>
            <button className={ownOccupant?.ready ? "selected" : "primary"} disabled={busy} onClick={() => void setRoomReady(!ownOccupant?.ready)}>{ownOccupant?.ready ? "取消准备" : "我已准备"}</button>
            {client.room?.adminToken && <button className="primary" disabled={busy || !roomReady} onClick={() => void startRoom()}>开始游戏</button>}
            <button disabled={busy} onClick={() => void leaveOrCloseRoom()}>{client.room?.adminToken ? "关闭房间" : "离开房间"}</button>
          </div>}
      </>}
    </section> : roomCode && !game ? <section className="empty"><h2>{roomInfo?.room.spectators ? "正在载入旁观视图…" : "此房间不允许旁观"}</h2><p>{roomInfo?.room.spectators ? "游戏状态变化后会自动同步。" : "对局已经开始，只有已入座的设备可以进入。"}</p></section> : !game ? <section className="welcome">
      <article><h2>{client.session ? "正在恢复对局…" : "本机调试对局"}</h2><p>上方可新建本机对局并切换所有视角，适合规则调试。</p></article>
      <article><h2>创建局域网房间</h2><p>每台手机只会看到自己的手牌和私密信息。</p>
        <label>昵称<input maxLength={24} value={nickname} onChange={event => setNickname(event.target.value)} placeholder="你的显示名称" /></label>
        <label>主人公玩家人数<select aria-label="主人公玩家人数" value={effectiveProtagonistCount} disabled={module === "LL"} onChange={event => {
          const count = Number(event.target.value) as 1 | 2 | 3;
          setProtagonistCount(count);
          if (preferredSeat !== "m" && !(["a", "b", "c"] as Seat[]).slice(0, count).includes(preferredSeat)) setPreferredSeat("m");
        }}><option value="1">1 人（控制全部主人公）</option><option value="2">2 人（轮流领队并代管 C）</option><option value="3">3 人</option></select></label>
        {module === "LL" && <small className="muted">Last Liar 必须由三名主人公玩家参与。</small>}
        <label>你的参与者席位<select value={preferredSeat} onChange={event => setPreferredSeat(event.target.value as Seat)}><option value="m">剧作家</option>{(["a", "b", "c"] as Seat[]).slice(0, effectiveProtagonistCount).map(seat => <option value={seat} key={seat}>主人公 {seat.toUpperCase()}</option>)}</select></label>
        <label className="checkbox"><input type="checkbox" checked={allowSpectators} onChange={event => setAllowSpectators(event.target.checked)} />允许未入座者旁观公开棋盘</label>
        {!nickname.trim() && <small className="muted">请先输入昵称，才能创建或加入房间。</small>}
        <button className="primary" disabled={busy || !nickname.trim()} onClick={() => void createRoom()}>创建房间</button>
        <div className="join-code"><input aria-label="房间码" inputMode="numeric" pattern="[0-9]*"
          value={roomEntry} onChange={event => setRoomEntry(event.target.value.replace(/\D/g, "").slice(0, 6))}
          placeholder="输入 6 位数字" /><button disabled={!/^\d{6}$/.test(roomEntry)} onClick={() => enterRoom(roomEntry)}>进入房间</button></div>
      </article>
    </section> : <>
      {roomInfo && <section className="room-bar"><strong>房间 {roomInfo.room.code}</strong><span>你的席位：{ownSeat ? game.labels.actors[ownSeat] : "旁观者"}</span>
        {roomInfo.room.protagonist_count === 2 && <span>今日真人领队：{roomInfo.room.seats[roomInfo.room.human_leader]?.nickname}（代管 C）</span>}
        {roomInfo.room.protagonist_count === 1 && <span>主人公玩家控制 A/B/C</span>}
        <span>{roomInfo.room.required_seats.filter(seat => roomInfo.room.seats[seat]?.connected).length}/{roomInfo.room.required_seats.length} 在线</span>
        <button onClick={returnToLobby}>返回大厅</button></section>}
      {!roomCode && <nav className="viewer-tabs" aria-label="调试视角">{seats.map(seat => <button className={viewer === seat ? "active" : ""} disabled={busy} key={seat} onClick={() => switchViewer(seat)}>{seat === "spectator" ? "公开视角" : game.labels.actors[seat]}</button>)}</nav>}
      <section className="status-strip">
        <div><small>{game.title} · {game.module_name}</small><strong>轮回 {game.loop}/{game.loops} · 第 {game.round}/{game.days} 天</strong></div>
        <div><small>{game.phase_name}</small><strong>{game.timepoint}</strong></div>
        <div><small>当前操作者</small><strong>{game.controller ? game.labels.actors[game.controller] : "结算完成"}</strong></div>
        <div><small>{roomInfo?.room.protagonist_count === 2 ? "逻辑领队 / 真人领队" : "领队与讨论"}</small><strong>{roomInfo?.room.protagonist_count === 2
          ? `${game.labels.actors[game.leader]} / ${roomInfo.room.seats[roomInfo.room.human_leader]?.nickname}`
          : `${game.labels.actors[game.leader]} · ${game.table_talk ? "允许讨论" : "禁止讨论"}`}</strong></div>
      </section>
      {game.winner && <section className="outcome" role="status">{winnerName(game)}</section>}
      <section className={`turn-banner ${offers.length ? "active" : "waiting"}`} aria-live="polite">
        <div><small>{offers.length ? "YOUR TURN" : "CURRENT TURN"}</small><strong>{offers.length
          ? `现在轮到你以${game.labels.actors[offers[0].actor as Seat]}身份行动`
          : game.controller ? `等待${game.labels.actors[game.controller]}行动` : "正在结算阶段效果"}</strong></div>
        <span>{game.phase_name} · {game.table_talk ? "允许讨论" : "禁止讨论"}</span>
      </section>
      <div className="workspace"><div className="play-column"><Actions key={`${viewer}:${offers.map(item => item.id).join(",")}`} offers={offers} catalog={catalog} game={game} busy={busy} onAction={act} /></div><aside>
        {game.protagonist_secret && <section className="panel personal-secret"><h2>你的 Last Liar 秘密</h2><strong>秘密 {game.protagonist_secret}</strong><p>此编号只对当前主人公可见，请勿向其他玩家展示。</p></section>}
        {game.secret && <section className="panel secret"><h2>剧作家资料</h2><p>规则 Y：{itemName(catalog?.plots, game.secret.main_plot)}</p><p>规则 X：{game.secret.subplots.map(id => itemName(catalog?.plots, id)).join("、")}</p><p>本轮实际天数：{game.secret.current_loop_days}</p>
          <details><summary>身份配置</summary>{Object.entries(game.secret.roles).map(([id, role]) => <p key={id}>{game.characters[id]?.name ?? id}：{itemName(catalog?.roles, role)}{game.secret?.hidden_roles?.[id] ? `／里身份 ${itemName(catalog?.roles, game.secret.hidden_roles[id])}` : ""}</p>)}</details>
          <details><summary>事件当事人</summary>{game.secret.incidents.map((incident, index) => <p key={index}>第 {String(incident.day)} 天 · {itemName(catalog?.incidents, incident.kind)}：{targetName(game, incident.culprit)}</p>)}</details>
          {(game.secret.ability_day_used.length > 0 || game.secret.ability_loop_used.length > 0) && <details><summary>完整能力使用记录</summary>
            {game.secret.ability_day_used.map(key => <p key={`day-${key}`}>今日：{abilityUseName(game, key, catalog)}</p>)}
            {game.secret.ability_loop_used.map(key => <p key={`loop-${key}`}>本轮：{abilityUseName(game, key, catalog)}</p>)}
          </details>}
        </section>}
        <section className="panel"><h2>事件日程</h2>{game.schedule.map(item => {
          const record = game.incidents.find(candidate => candidate.day === item.day);
          const status = !record ? "未结算" : record.happened ? (record.effective ? "已发生" : "发生但无效果") : "未发生";
          const board = "board" in item ? ` · ${game.labels.locations[item.board as keyof typeof game.locations]}` : "";
          return <p key={`${item.day}-${item.kind}`}>第 {item.day} 天 · {itemName(catalog?.incidents, item.kind)}{board} · {status}</p>;
        })}</section>
        <Cards game={game} catalog={catalog} viewer={viewer} /><Knowledge game={game} catalog={catalog} /><RulesReference catalog={catalog} />
        <PublicLog game={game} catalog={catalog} />
        <section className="panel tools">{(!roomCode || client.room?.adminToken) && <><button onClick={saveSnapshot}>保存 JSON</button><button onClick={() => void readReplay()}>查看回放</button><button onClick={() => void readReplay(true)}>导出回放</button></>}<button onClick={() => void refresh()}>刷新</button></section>
      </aside></div>
      {replayText && <ReplayDialog text={replayText} onClose={() => setReplayText("")} />}
    </>}
  </main>;
}
