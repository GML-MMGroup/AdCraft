export const imageBase = "/assets/";

export const images = [
  "card1.webp",
  "card2.webp",
  "card3.webp",
  "card4.webp",
  "card5.webp",
  "card6.webp",
  "card7.webp",
  "card8.webp",
];

export const demoProjects = [
  { name: "Perfume Launch Film", time: "Updated today", favorite: true, img: images[0] },
  { name: "Summer Drink Campaign", time: "Updated yesterday", favorite: false, img: images[1] },
  { name: "Han Dynasty Concept", time: "Updated Jun 02", favorite: true, img: images[2] },
  { name: "Skincare Motion Board", time: "Updated May 29", favorite: false, img: images[3] },
  { name: "Urban Runner Ad", time: "Updated May 22", favorite: false, img: images[4] },
];

export const demoAssets = {
  role: [
    { name: "Muse Host", meta: "Character · updated today", favorite: true },
    { name: "Product Narrator", meta: "Character · 12 references", favorite: false },
    { name: "Studio Model", meta: "Character · last used yesterday", favorite: true },
  ],
  scene: [
    { name: "Morning Kitchen", meta: "Scene · warm interior", favorite: false },
    { name: "Glass Retail Table", meta: "Scene · product display", favorite: true },
    { name: "Misty Outdoor Alley", meta: "Scene · cinematic", favorite: false },
  ],
};

export const trashItems = [
  { type: "project", name: "Old Fragrance Draft", meta: "Deleted 2 days ago", img: images[5] },
  { type: "role", name: "Unused Spokesperson", meta: "Deleted 5 days ago", img: images[6] },
  { type: "scene", name: "Blue Storefront", meta: "Deleted 1 week ago", img: images[7] },
];

export function imageUrl(name: string) {
  return `url("${imageBase}${name}")`;
}

export function imageSrc(name: string) {
  return `${imageBase}${name}`;
}
