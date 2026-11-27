import { renderSocialImage, socialImageContentType, socialImageSize } from "./social-card";
import { socialImageAlt } from "./site-metadata";

export const alt = socialImageAlt;
export const size = socialImageSize;
export const contentType = socialImageContentType;

export default function TwitterImage() {
  return renderSocialImage();
}
