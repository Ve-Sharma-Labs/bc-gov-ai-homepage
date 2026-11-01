import { clsx, type ClassValue } from "clsx";
import type { MouseEvent } from "react";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function retainComposerFocus(event: MouseEvent<HTMLElement>) {
  // Blurring the dock can move an inline target between pointer-down and click.
  if (event.button === 0) event.preventDefault();
}
