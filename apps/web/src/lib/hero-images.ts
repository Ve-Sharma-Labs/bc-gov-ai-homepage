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
    id: "vancouver-waterfront",
    src: "/images/bc/vancouver-waterfront-1600.webp",
    mobileSrc: "/images/bc/vancouver-waterfront-800.webp",
    alt: "Boats and towers along Vancouver's waterfront reflected in the water at dusk.",
    place: "Vancouver, British Columbia",
    photographer: "Aditya Chinchure",
    sourceUrl: "https://unsplash.com/photos/a-city-skyline-with-boats-f2HurUPuVyA",
    photographerUrl: "https://unsplash.com/@adityachinchure",
    width: 1600,
    height: 1067,
    position: "50% 48%",
  },
  {
    id: "garibaldi-lake",
    src: "/images/bc/garibaldi-lake-1600.webp",
    mobileSrc: "/images/bc/garibaldi-lake-800.webp",
    alt: "Turquoise Garibaldi Lake below forested slopes and snow-covered mountains in British Columbia.",
    place: "Garibaldi Lake, British Columbia",
    photographer: "Vlad Namashko",
    sourceUrl: "https://unsplash.com/photos/a-lake-surrounded-by-mountains-and-trees-yXIfv6rQDuQ",
    photographerUrl: "https://unsplash.com/@nvv",
    width: 1600,
    height: 1067,
    position: "50% 42%",
  },
  {
    id: "tofino-coast",
    src: "/images/bc/tofino-coast-1600.webp",
    mobileSrc: "/images/bc/tofino-coast-800.webp",
    alt: "Ocean waves and a pink evening sky reflected on a beach in Tofino.",
    place: "Tofino, British Columbia",
    photographer: "Frederic Leblanc",
    sourceUrl: "https://unsplash.com/photos/photography-of-shore-line-xUd_HMODlDg",
    photographerUrl: "https://unsplash.com/@_thewhiteguy",
    width: 1600,
    height: 1067,
    position: "50% 56%",
  },
  {
    id: "okanagan-lake",
    src: "/images/bc/okanagan-lake-1600.webp",
    mobileSrc: "/images/bc/okanagan-lake-800.webp",
    alt: "Okanagan Lake and surrounding hills seen past pine trees near Peachland.",
    place: "Peachland, British Columbia",
    photographer: "Robbie Down",
    sourceUrl: "https://unsplash.com/photos/green-trees-near-body-of-water-during-daytime-zppGPIF-aqo",
    photographerUrl: "https://unsplash.com/@robbiedown",
    width: 1600,
    height: 900,
    position: "50% 46%",
  },
  {
    id: "victoria-parliament",
    src: "/images/bc/victoria-parliament-2400.webp",
    mobileSrc: "/images/bc/victoria-parliament-1200.webp",
    alt: "British Columbia's Parliament Buildings in Victoria, with a Canadian flag and fountain in daylight.",
    place: "Victoria, British Columbia",
    photographer: "Brian Zhu",
    sourceUrl: "https://unsplash.com/photos/the-british-columbia-parliament-buildings-are-showcased-0IM71KfH3mo",
    photographerUrl: "https://unsplash.com/@dogrod",
    width: 2400,
    height: 1600,
    position: "50% 50%",
  },
];
