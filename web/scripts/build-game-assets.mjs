import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import process from "node:process";
import sharp from "sharp";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(webRoot, "..");
const sourceRoot = path.join(repositoryRoot, "resources");
const outputRoot = path.join(webRoot, "public", "game-assets");
const manifestPath = path.join(webRoot, "src", "generated", "game-assets.json");

const characterNames = {
  student: "男学生", girl: "女学生", rich: "大小姐", class_rep: "班长",
  teacher: "教师", maiden: "巫女", outsider: "异界人", police: "刑警",
  worker: "职员", informer: "情报商", idol: "偶像", journalist: "媒体人",
  forensic: "鉴识官", doctor: "医生", patient: "住院患者", nurse: "护士",
  soldier: "军人", henchman: "手下",
};

const cardOrder = {
  "剧作家手牌": [
    ["m", "p1a"], ["m", "p1b"], ["m", "p-1"], ["m", "fp"], ["m", "fg"],
    ["m", "i1"], ["m", "i2"], ["m", "v"], ["m", "h"], ["m", "d"],
  ],
  "主人公A手牌": [
    ["a", "p1"], ["a", "p-1"], ["a", "g1"], ["a", "g2"],
    ["a", "fi"], ["a", "v"], ["a", "h"], ["a", "fm"],
  ],
  "主人公B手牌": [
    ["b", "p1"], ["b", "p-1"], ["b", "g1"], ["b", "g2"],
    ["b", "fi"], ["b", "v"], ["b", "h"], ["b", "fm"],
  ],
  "主人公C手牌": [
    ["c", "p1"], ["c", "p-1"], ["c", "g1"], ["c", "g2"],
    ["c", "fi"], ["c", "v"], ["c", "h"], ["c", "fm"],
  ],
  "追加牌": [
    ["m", "ahr_d1"], ["m", "ahr_g1"],
    ["a", "ahr_p2"], ["a", "ahr_h1"], ["b", "ahr_p2"], ["b", "ahr_h1"],
    ["c", "ahr_p2"], ["c", "ahr_h1"],
  ],
};

function value(block, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return block.match(new RegExp(`<data(?:\\s+[^>]*)?\\sname="${escaped}"[^>]*>([^<]*)</data>`))?.[1]?.trim() ?? "";
}

function parseStacks(xml) {
  const stacks = new Map();
  for (const match of xml.matchAll(/<card-stack\b[\s\S]*?<\/card-stack>/g)) {
    const block = match[0];
    const stackName = block.match(/<data name="card-stack">[\s\S]*?<data name="common">[\s\S]*?<data name="name">([^<]+)<\/data>/)?.[1]?.trim();
    if (!stackName) continue;
    const cards = [];
    for (const card of block.matchAll(/<(?:rooper-card|card)(?=[\s>])[\s\S]*?<\/(?:rooper-card|card)>/g)) {
      const front = value(card[0], "front");
      const name = card[0].match(/<data name="common">[\s\S]*?<data name="name">([^<]+)<\/data>/)?.[1]?.trim() ?? "";
      if (/^[a-f0-9]{64}$/.test(front)) cards.push({ name, hash: front });
    }
    stacks.set(stackName, cards);
  }
  return stacks;
}

const xml = await readFile(path.join(sourceRoot, "data.xml"), "utf8");
const stacks = parseStacks(xml);
const characterCards = new Map((stacks.get("角色一览") ?? []).map(card => [card.name, card.hash]));
const manifest = { characters: {}, cards: { m: {}, a: {}, b: {}, c: {} } };

for (const [id, name] of Object.entries(characterNames)) {
  const hash = characterCards.get(name);
  if (!hash) throw new Error(`data.xml 缺少角色图片：${name} (${id})`);
  manifest.characters[id] = hash;
}

for (const [stackName, entries] of Object.entries(cardOrder)) {
  const sourceCards = stacks.get(stackName) ?? [];
  if (sourceCards.length !== entries.length) {
    throw new Error(`${stackName} 应有 ${entries.length} 张牌，实际读取到 ${sourceCards.length} 张`);
  }
  entries.forEach(([seat, id], index) => { manifest.cards[seat][id] = sourceCards[index].hash; });
}

const hashes = new Set([
  ...Object.values(manifest.characters),
  ...Object.values(manifest.cards).flatMap(cards => Object.values(cards)),
]);
await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
await mkdir(path.dirname(manifestPath), { recursive: true });
for (const hash of [...hashes].sort()) {
  await sharp(path.join(sourceRoot, `${hash}.png`))
    .resize({ width: 180, withoutEnlargement: true })
    .webp({ quality: 76, effort: 5 })
    .toFile(path.join(outputRoot, `${hash}.webp`));
}
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
process.stdout.write(`已生成 ${hashes.size} 张 Web 素材和映射表。\n`);
