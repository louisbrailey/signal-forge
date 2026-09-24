// Block + tile registry. Tiles are 16×16 pixel-art images packed into the atlas (textures.ts).

export enum T {
  GrassTop, GrassSide, Dirt, Stone, Cobble, Sand, Gravel, OakLog,
  OakLogTop, OakLeaves, OakPlanks, DarkPlanks, DarkLog, DarkLogTop, StoneBricks, MossyBricks,
  Gold, PurpleWool, SmoothStone, PathTop, CraftTop, CraftSide, CraftFront, FurnaceFront,
  FurnaceSide, FurnaceTop, Bookshelf, EnchantTop, EnchantSide, Obsidian, Glass, Lantern,
  FlowerRed, FlowerYellow, FlowerBlue, FlowerPink, TallGrass, BlossomLeaves, Water, HayTop,
  HaySide, Bricks, Quartz, MossyCobble, BarrelTop, BarrelSide, Amethyst, ChestFront,
  ChestSide, ChestTop, RedWool, WhiteWool, CoarseDirt, AnvilTop, LecternTop, LecternSide,
  IronBlock, Fern, PathSide, GoldTrim, Sapling, Mushroom, YellowWool, Wheat,
  FarmTop, Count,
}

export type BlockKind = 'solid' | 'cutout' | 'plant' | 'glow';

export interface BlockDef {
  name: string;
  /** tiles per face: [+x, -x, +y, -y, +z, -z] */
  tiles: [number, number, number, number, number, number];
  kind: BlockKind;
}

function all(t: number): BlockDef['tiles'] {
  return [t, t, t, t, t, t];
}
function column(side: number, top: number, bottom = top): BlockDef['tiles'] {
  return [side, side, top, bottom, side, side];
}
function front(side: number, top: number, fr: number, bottom = top): BlockDef['tiles'] {
  // front faces +z (south, toward the village / default camera)
  return [side, side, top, bottom, fr, side];
}

export const B = {
  Air: 0,
  Grass: 1,
  Dirt: 2,
  Stone: 3,
  Cobble: 4,
  Sand: 5,
  Gravel: 6,
  OakLog: 7,
  OakLeaves: 8,
  OakPlanks: 9,
  DarkPlanks: 10,
  DarkLog: 11,
  StoneBricks: 12,
  MossyBricks: 13,
  Gold: 14,
  PurpleWool: 15,
  SmoothStone: 16,
  Path: 17,
  Crafting: 18,
  Furnace: 19,
  Bookshelf: 20,
  Enchant: 21,
  Obsidian: 22,
  Glass: 23,
  Lantern: 24,
  FlowerRed: 25,
  FlowerYellow: 26,
  FlowerBlue: 27,
  FlowerPink: 28,
  TallGrass: 29,
  BlossomLeaves: 30,
  Hay: 31,
  Bricks: 32,
  Quartz: 33,
  MossyCobble: 34,
  Barrel: 35,
  Amethyst: 36,
  Chest: 37,
  RedWool: 38,
  WhiteWool: 39,
  CoarseDirt: 40,
  Anvil: 41,
  Lectern: 42,
  IronBlock: 43,
  Fern: 44,
  GoldTrim: 45,
  Mushroom: 46,
  YellowWool: 47,
  PlankPath: 48,
  Wheat: 49,
  Farmland: 50,
} as const;

export type BlockId = (typeof B)[keyof typeof B];

export const BLOCKS: BlockDef[] = [];
function def(id: number, name: string, tiles: BlockDef['tiles'], kind: BlockKind = 'solid'): void {
  BLOCKS[id] = { name, tiles, kind };
}

def(B.Air, 'air', all(0));
def(B.Grass, 'grass', column(T.GrassSide, T.GrassTop, T.Dirt));
def(B.Dirt, 'dirt', all(T.Dirt));
def(B.Stone, 'stone', all(T.Stone));
def(B.Cobble, 'cobblestone', all(T.Cobble));
def(B.Sand, 'sand', all(T.Sand));
def(B.Gravel, 'gravel', all(T.Gravel));
def(B.OakLog, 'oak log', column(T.OakLog, T.OakLogTop));
def(B.OakLeaves, 'oak leaves', all(T.OakLeaves), 'cutout');
def(B.OakPlanks, 'oak planks', all(T.OakPlanks));
def(B.DarkPlanks, 'dark planks', all(T.DarkPlanks));
def(B.DarkLog, 'dark log', column(T.DarkLog, T.DarkLogTop));
def(B.StoneBricks, 'stone bricks', all(T.StoneBricks));
def(B.MossyBricks, 'mossy bricks', all(T.MossyBricks));
def(B.Gold, 'gold block', all(T.Gold));
def(B.PurpleWool, 'purple wool', all(T.PurpleWool));
def(B.SmoothStone, 'smooth stone', all(T.SmoothStone));
def(B.Path, 'path', column(T.PathSide, T.PathTop, T.Dirt));
def(B.Crafting, 'crafting table', front(T.CraftSide, T.CraftTop, T.CraftFront, T.OakPlanks));
def(B.Furnace, 'furnace', front(T.FurnaceSide, T.FurnaceTop, T.FurnaceFront));
def(B.Bookshelf, 'bookshelf', column(T.Bookshelf, T.OakPlanks));
def(B.Enchant, 'enchanting table', column(T.EnchantSide, T.EnchantTop, T.Obsidian));
def(B.Obsidian, 'obsidian', all(T.Obsidian));
def(B.Glass, 'glass', all(T.Glass), 'cutout');
def(B.Lantern, 'lantern', all(T.Lantern), 'glow');
def(B.FlowerRed, 'poppy', all(T.FlowerRed), 'plant');
def(B.FlowerYellow, 'dandelion', all(T.FlowerYellow), 'plant');
def(B.FlowerBlue, 'cornflower', all(T.FlowerBlue), 'plant');
def(B.FlowerPink, 'tulip', all(T.FlowerPink), 'plant');
def(B.TallGrass, 'tall grass', all(T.TallGrass), 'plant');
def(B.BlossomLeaves, 'blossom leaves', all(T.BlossomLeaves), 'cutout');
def(B.Hay, 'hay bale', column(T.HaySide, T.HayTop));
def(B.Bricks, 'bricks', all(T.Bricks));
def(B.Quartz, 'quartz', all(T.Quartz));
def(B.MossyCobble, 'mossy cobblestone', all(T.MossyCobble));
def(B.Barrel, 'barrel', column(T.BarrelSide, T.BarrelTop));
def(B.Amethyst, 'amethyst', all(T.Amethyst), 'glow');
def(B.Chest, 'chest', front(T.ChestSide, T.ChestTop, T.ChestFront));
def(B.RedWool, 'red wool', all(T.RedWool));
def(B.WhiteWool, 'white wool', all(T.WhiteWool));
def(B.CoarseDirt, 'coarse dirt', all(T.CoarseDirt));
def(B.Anvil, 'anvil', column(T.IronBlock, T.AnvilTop));
def(B.Lectern, 'lectern', column(T.LecternSide, T.LecternTop, T.OakPlanks));
def(B.IronBlock, 'iron block', all(T.IronBlock));
def(B.Fern, 'fern', all(T.Fern), 'plant');
def(B.GoldTrim, 'gold trim', all(T.GoldTrim));
def(B.Mushroom, 'mushroom', all(T.Mushroom), 'plant');
def(B.YellowWool, 'yellow wool', all(T.YellowWool));
def(B.PlankPath, 'plank path', column(T.OakPlanks, T.OakPlanks));
def(B.Wheat, 'wheat', all(T.Wheat), 'plant');
def(B.Farmland, 'farmland', column(T.Dirt, T.FarmTop, T.Dirt));

/** Occludes neighbours for face culling & AO. */
export function isOpaque(id: number): boolean {
  return id !== 0 && BLOCKS[id].kind !== 'cutout' && BLOCKS[id].kind !== 'plant';
}
export function isSolid(id: number): boolean {
  return id !== 0 && BLOCKS[id].kind !== 'plant';
}
