import type { CatalogResponse, GameView } from "./api/types";

export function itemName(items: Array<{ id: string; name: string }> | undefined, id: unknown) {
  return items?.find(item => item.id === id)?.name ?? String(id ?? "—");
}

export function abilityUseName(game: GameView, key: string, catalog?: CatalogResponse | null) {
  const parts = key.split(":");
  if (parts[0] === "goodwill" && parts.length >= 3) {
    const character = parts[1];
    const definition = game.characters[character]?.abilities.find(item => item.id === parts[2]);
    return `${game.characters[character]?.name ?? character} · ${definition?.text ?? parts[2]}`;
  }
  const roleIndex = parts[0] === "mandatory" || parts[0] === "role" ? 1 : 0;
  const role = parts[roleIndex];
  const character = [...parts].reverse().find(part => part in game.characters);
  const roleName = itemName(catalog?.roles, role);
  if (character) return `${game.characters[character].name} · ${roleName}`;
  if (parts[0] === "plot") {
    const plot = catalog?.plots.find(item => item.id === parts[1]);
    return `规则能力 · ${plot?.name ?? parts.slice(1).join(" · ")}`;
  }
  if (key === "zombie:kill") return "丧尸强制能力";
  return `${roleName}能力`;
}
