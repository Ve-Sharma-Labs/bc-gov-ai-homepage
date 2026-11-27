export const webRoot: string;
export function publicProjection(pack: Record<string, any>): Record<string, any>;
export function loadPresentation(id?: string, packsRoot?: string): { id: string };
export function prepareJurisdiction(options?: { production?: boolean }): string;
export function assertRuntimeJurisdiction(selected: string, requested?: string): void;
export function stampJurisdiction(id: string): void;
