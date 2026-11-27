export interface HeroImage {
  id: string;
  src: string;
  mobileSrc: string;
  alt: string;
  place: string;
  photographer: string;
  sourceUrl: string;
  photographerUrl: string;
  width: number;
  height: number;
  position: string;
}

export const heroImages: HeroImage[] = [
  {
    id: "saskatchewan-fields",
    src: "/images/sk/saskatchewan-fields-1600.webp",
    mobileSrc: "/images/sk/saskatchewan-fields-800.webp",
    alt: "An aerial view of Saskatchewan crop fields in two shades of green and yellow, divided by a straight road.",
    place: "Saskatchewan farmland",
    photographer: "Ruvim Kerimov",
    sourceUrl: "https://unsplash.com/photos/an-aerial-view-of-a-green-field-with-a-white-line-GuCNRdpemxc",
    photographerUrl: "https://unsplash.com/@ruvimkerimov",
    width: 1600,
    height: 1200,
    position: "50% 50%",
  },
  {
    id: "saskatoon-river",
    src: "/images/sk/saskatoon-river-1600.webp",
    mobileSrc: "/images/sk/saskatoon-river-800.webp",
    alt: "The South Saskatchewan River and a bridge beneath a bright, cloud-filled sky.",
    place: "South Saskatchewan River, Saskatoon",
    photographer: "Kaz Vogel",
    sourceUrl: "https://unsplash.com/photos/a-body-of-water-with-a-bridge-in-the-background-jWGKI_oEG30",
    photographerUrl: "https://unsplash.com/@kazev",
    width: 1600,
    height: 1200,
    position: "50% 50%",
  },
  {
    id: "regina-sunset",
    src: "/images/sk/regina-sunset-1600.webp",
    mobileSrc: "/images/sk/regina-sunset-800.webp",
    alt: "A domed building silhouetted against the setting sun, with water in the foreground.",
    place: "Regina, Saskatchewan",
    photographer: "Tandem X Visuals",
    sourceUrl: "https://unsplash.com/photos/sunset-silhouettes-the-buildings-dome-and-horizon-DdRCJgdpHPo",
    photographerUrl: "https://unsplash.com/@tandemxvisuals",
    width: 1600,
    height: 1200,
    position: "50% 50%",
  },
  {
    id: "grasslands",
    src: "/images/sk/grasslands-1600.webp",
    mobileSrc: "/images/sk/grasslands-800.webp",
    alt: "Low, rolling grassland hills with dry grasses and scattered trees beneath an open sky.",
    place: "Grasslands National Park, Saskatchewan",
    photographer: "Andrew Darlington",
    sourceUrl: "https://unsplash.com/photos/rolling-hills-with-dry-grass-d6JfGN6k0Ac",
    photographerUrl: "https://unsplash.com/@andrewdarlington",
    width: 1600,
    height: 1200,
    position: "50% 50%",
  },
  {
    id: "pinehouse-aurora",
    src: "/images/sk/pinehouse-aurora-1600.webp",
    mobileSrc: "/images/sk/pinehouse-aurora-800.webp",
    alt: "A green aurora reflected in still water at night.",
    place: "Pinehouse Lake, Saskatchewan",
    photographer: "Dre Erwin",
    sourceUrl: "https://unsplash.com/photos/the-aurora-bore-is-reflected-in-the-water-at-night-mGY-pzwunLs",
    photographerUrl: "https://unsplash.com/@dreerwin",
    width: 1600,
    height: 1200,
    position: "50% 50%",
  },
];
