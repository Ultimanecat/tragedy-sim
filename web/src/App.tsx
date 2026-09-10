import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiClient, ApiError, type StoredSession } from "./api/client";
import type { ActionOffer, CatalogResponse, GameView, ModuleId, ModuleSummary, Seat, Viewer } from "./api/types";

const SESSION_KEY = "tragedy-sim.local-session.v1";
const seats: Viewer[] = ["spectator", "m", "a", "b", "c"];
const locations = ["hospital", "shrine", "city", "school"] as const;

function loadSession(): StoredSession | null {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY) || "null") as StoredSession | null; }
  catch { return null; }
}

function download(name: string, contents: string, type: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; anchor.click();
  URL.revokeObjectURL(url);
}

function itemName(items: Array<{ id: string; name: string }> | undefined, id: unknown) {
  return items?.find(item => item.id === id)?.name ?? String(id ?? "—");
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

function abilityUseName(game: GameView, key: string) {
  const [, character, ability] = key.split(":");
  const definition = game.characters[character]?.abilities.find(item => item.id === ability);
  return `${game.characters[character]?.name ?? character} · ${definition?.text ?? ability}`;
}

export function Board({ game, catalog }: { game: GameView; catalog: CatalogResponse | null }) {
  const cardName = (actor: string, id: unknown) => id
    ? itemName(catalog?.cards[actor as Seat], id) : "暗牌";
  const boardCounter = game.module === "HSA" ? "尸体" : "密谋";
  return <>
    <section className="board" aria-label="游戏版图">
      {locations.map(location => <article className={`location location-${location}`} key={location}>
        <header><h2>{game.labels.locations[location]}</h2><span>{boardCounter} {game.locations[location]}{game.board_ex[location] ? ` · 诅咒 ${game.board_ex[location]}` : ""}</span></header>
        <div className="characters">
          {Object.values(game.characters).filter(character => character.location === location).map(character =>
            <div className={`character ${character.alive ? "" : "dead"}`} key={character.id}>
              <div className="character-title"><strong>{character.name}</strong><small>{character.alive ? "存活" : "死亡"}</small></div>
              <div className="counters">
                <span>友好 {character.goodwill}</span><span>不安 {character.paranoia}/{character.paranoia_limit}</span>
                <span>密谋 {character.intrigue}</span>
                {character.hope > 0 && <span>希望 {character.hope}</span>}
                {character.despair > 0 && <span>绝望 {character.despair}</span>}
                {character.guard > 0 && <span>护卫 {character.guard}</span>}
                {character.ex_cards > 0 && <span>{game.module === "HSA" ? "诅咒" : "Ex"} {character.ex_cards}</span>}
                {character.friended_token && <span>交友完毕</span>}
                {character.death_token && <span>死亡完毕</span>}
              </div>
              <details className="character-reference"><summary>角色资料</summary>
                <p>属性：{character.traits.join("、") || "无"}</p>
                <p>禁行：{character.forbidden.map(id => game.labels.locations[id]).join("、") || "无"}</p>
                {character.abilities.map(ability => <p key={`${ability.id}-${ability.threshold}`}>
                  友好 {ability.threshold}：{ability.text}{ability.once ? "（限次）" : ""}{ability.unrefusable ? "（不可拒绝）" : ""}
                </p>)}
                {character.passive && <p>被动：{character.passive}</p>}
              </details>
            </div>)}
        </div>
      </article>)}
    </section>
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
  return <section className="panel"><h2>手牌与公开留置</h2>
    {viewer !== "spectator" && <><h3>{game.labels.actors[viewer]}手牌</h3><div className="card-list">
      {game.hand.map(id => <span key={id}>{cardName(viewer, id)}</span>)}
    </div></>}
    {!discarded.length && <p className="muted">目前没有公开留置牌。</p>}
    {discarded.map(([seat, cards]) => <p key={seat}>{game.labels.actors[seat as Seat]}：
      {cards.map(id => cardName(seat as Seat, id)).join("、")}</p>)}
  </section>;
}

export function Actions({ offers, catalog, game, busy, onAction }: {
  offers: ActionOffer[]; catalog: CatalogResponse | null; game: GameView;
  busy: boolean; onAction: (offer: ActionOffer) => void;
}) {
  const [selectedCard, setSelectedCard] = useState<string | null>(null);
  const [selectedGuess, setSelectedGuess] = useState<string | null>(null);
  const [selected, setSelected] = useState<ActionOffer | null>(null);
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
  const actor = offers[0]?.actor;
  const choices = selectedCard ? playGroups.get(selectedCard) ?? [] : [];
  const guesses = selectedGuess ? guessGroups.get(selectedGuess) ?? [] : [];
  return <section className="panel actions-panel">
    <h2>可执行行动</h2>
    {!offers.length && <p className="muted">当前视角没有可执行行动。</p>}
    {!!others.length && <div className="action-grid">{others.map(offer =>
      <button className={selected?.id === offer.id ? "selected" : ""} disabled={busy} key={offer.id}
        onClick={() => setSelected(offer)}>{offer.label}</button>)}</div>}
    {!!playGroups.size && <>
      <p className="step-label">1. 选择手牌</p><div className="hand">
        {[...playGroups].map(([card, available]) => <button className={selectedCard === card ? "selected" : ""}
          disabled={busy} key={card} onClick={() => { setSelectedCard(card); setSelected(null); }}>
          <strong>{itemName(actor ? catalog?.cards[actor] : undefined, card)}</strong><small>{available.length} 个合法目标</small>
        </button>)}
      </div>
      {selectedCard && <><p className="step-label">2. 选择目标</p><div className="action-grid">
        {choices.map(offer => <button className={selected?.id === offer.id ? "selected" : ""}
          disabled={busy} key={offer.id} onClick={() => setSelected(offer)}>
          {targetName(game, offer.parameters.target) || offer.label}</button>)}
      </div></>}
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
  </section>;
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
      已声明能力：{abilityUseName(game, key)}{game.ability_loop_used.includes(key) ? "（本轮限次已使用）" : "（今日已使用）"}</p>)}
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

export default function App() {
  const [client] = useState(() => new ApiClient(loadSession()));
  const [modules, setModules] = useState<ModuleSummary[]>([]);
  const [module, setModule] = useState<ModuleId>("BTX");
  const [viewer, setViewer] = useState<Viewer>("spectator");
  const [game, setGame] = useState<GameView | null>(null);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [offers, setOffers] = useState<ActionOffer[]>([]);
  const [replayText, setReplayText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const persist = useCallback(() => {
    if (client.session) localStorage.setItem(SESSION_KEY, JSON.stringify(client.session));
  }, [client]);

  const refresh = useCallback(async (nextViewer = viewer) => {
    if (!client.session) return;
    setBusy(true); setError("");
    try {
      const response = await client.view(nextViewer);
      setGame(response.state);
      const actor = response.state.controller;
      setOffers(actor && actor === nextViewer ? (await client.actions(actor)).actions : []);
      persist();
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "读取对局失败");
    } finally { setBusy(false); }
  }, [client, persist, viewer]);

  useEffect(() => { client.modules().then(result => setModules(result.modules)).catch(() => setError("无法读取规则集目录")); }, [client]);
  useEffect(() => {
    if (!client.session) return;
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [client, refresh]);
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

  return <main>
    <header className="masthead"><div><p className="eyebrow">TRAGEDY LOOPER</p><h1>悲剧轮回</h1></div><div className="new-game">
      <select aria-label="规则集" value={module} onChange={event => setModule(event.target.value as ModuleId)}>
        {modules.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
      <button className="primary" disabled={busy} onClick={createGame}>新建对局</button>
      <label className="file-button">载入存档/剧本<input type="file" accept="application/json" onChange={event => event.target.files?.[0] && void restore(event.target.files[0])} /></label>
    </div></header>
    {error && <div className="error" role="alert">{error}</div>}
    {!game ? <section className="empty"><h2>{client.session ? "正在恢复对局…" : "选择规则集，开始一次轮回"}</h2><p>规则判断全部由本机 Python 服务完成。</p></section> : <>
      <nav className="viewer-tabs" aria-label="调试视角">{seats.map(seat => <button className={viewer === seat ? "active" : ""} disabled={busy} key={seat} onClick={() => switchViewer(seat)}>{seat === "spectator" ? "公开视角" : game.labels.actors[seat]}</button>)}</nav>
      <section className="status-strip">
        <div><small>{game.title} · {game.module_name}</small><strong>轮回 {game.loop}/{game.loops} · 第 {game.round}/{game.days} 天</strong></div>
        <div><small>{game.phase_name}</small><strong>{game.timepoint}</strong></div>
        <div><small>当前操作者</small><strong>{game.controller ? game.labels.actors[game.controller] : "结算完成"}</strong></div>
        <div><small>领队与讨论</small><strong>{game.labels.actors[game.leader]} · {game.table_talk ? "允许讨论" : "禁止讨论"}</strong></div>
      </section>
      {game.winner && <section className="outcome" role="status">{winnerName(game)}</section>}
      <div className="workspace"><div><Board game={game} catalog={catalog} /><Actions key={`${viewer}:${offers.map(item => item.id).join(",")}`} offers={offers} catalog={catalog} game={game} busy={busy} onAction={act} /></div><aside>
        {game.protagonist_secret && <section className="panel personal-secret"><h2>你的 Last Liar 秘密</h2><strong>秘密 {game.protagonist_secret}</strong><p>此编号只对当前主人公可见，请勿向其他玩家展示。</p></section>}
        {game.secret && <section className="panel secret"><h2>剧作家资料</h2><p>规则 Y：{itemName(catalog?.plots, game.secret.main_plot)}</p><p>规则 X：{game.secret.subplots.map(id => itemName(catalog?.plots, id)).join("、")}</p><p>本轮实际天数：{game.secret.current_loop_days}</p>
          <details><summary>身份配置</summary>{Object.entries(game.secret.roles).map(([id, role]) => <p key={id}>{game.characters[id]?.name ?? id}：{itemName(catalog?.roles, role)}{game.secret?.hidden_roles?.[id] ? `／里身份 ${itemName(catalog?.roles, game.secret.hidden_roles[id])}` : ""}</p>)}</details>
          <details><summary>事件当事人</summary>{game.secret.incidents.map((incident, index) => <p key={index}>第 {String(incident.day)} 天 · {itemName(catalog?.incidents, incident.kind)}：{targetName(game, incident.culprit)}</p>)}</details>
          {(game.secret.ability_day_used.length > 0 || game.secret.ability_loop_used.length > 0) && <details><summary>完整能力使用记录</summary>
            {game.secret.ability_day_used.map(key => <p key={`day-${key}`}>今日：{abilityUseName(game, key)}</p>)}
            {game.secret.ability_loop_used.map(key => <p key={`loop-${key}`}>本轮：{abilityUseName(game, key)}</p>)}
          </details>}
          {!!game.secret.loss_reasons.length && <details><summary>内部失败诊断</summary>{game.secret.loss_reasons.map((reason, index) => <p key={index}>{reason}</p>)}</details>}
        </section>}
        <section className="panel"><h2>事件日程</h2>{game.schedule.map(item => {
          const record = game.incidents.find(candidate => candidate.day === item.day);
          const status = !record ? "未结算" : record.happened ? (record.effective ? "已发生" : "发生但无效果") : "未发生";
          const board = "board" in item ? ` · ${game.labels.locations[item.board as keyof typeof game.locations]}` : "";
          return <p key={`${item.day}-${item.kind}`}>第 {item.day} 天 · {itemName(catalog?.incidents, item.kind)}{board} · {status}</p>;
        })}</section>
        <Cards game={game} catalog={catalog} viewer={viewer} /><Knowledge game={game} catalog={catalog} /><RulesReference catalog={catalog} />
        <section className="panel log"><h2>公开日志</h2>{[...game.events].reverse().map((event, index) => <article key={`${event.loop}-${event.round}-${index}`}><small>{event.timepoint}</small><p>{event.message}</p>
          {Array.isArray(event.cards) && event.cards.map((placement, cardIndex) => {
            const card = placement as Record<string, unknown>;
            const actor = String(card.actor) as Seat;
            return <p className="log-detail" key={cardIndex}>{game.labels.actors[actor]}：
              {itemName(catalog?.cards[actor], card.card)} → {targetName(game, card.target)}</p>;
          })}</article>)}</section>
        <section className="panel tools"><button onClick={saveSnapshot}>保存 JSON</button><button onClick={() => void readReplay()}>查看回放</button><button onClick={() => void readReplay(true)}>导出回放</button><button onClick={() => void refresh()}>刷新</button></section>
      </aside></div>
      {replayText && <section className="replay" role="dialog" aria-label="只读回放"><header><h2>对局回放</h2><button onClick={() => setReplayText("")}>关闭</button></header><pre>{replayText}</pre></section>}
    </>}
  </main>;
}
