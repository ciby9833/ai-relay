export type EmotionId = 'boot' | 'wake' | 'idle' | 'sleep' | 'loading' | 'shutdown'
  | 'happy' | 'surprised' | 'thinking' | 'questioning' | 'sad' | 'focused' | 'proud'
  | 'listening' | 'searching' | 'working' | 'speaking' | 'waiting_approval' | 'waiting' | 'error' | 'completed' | 'offline';
export type MascotShape = 'blob' | 'wedge' | 'gem';
export interface MascotOptions { emotionId?: string; shape?: MascotShape; animated?: boolean }
export interface MascotController {
  setEmotion(value: unknown): void;
  setShape(value: unknown): void;
  setAnimated(value: boolean): void;
  handleAIMessage(message: unknown): EmotionId;
  replay(): void;
  destroy(): void;
}
export const EMOTIONS: Record<EmotionId, { group: 'lifecycle' | 'emotion' | 'agent'; labels: [string, string, string]; eyes: number[][]; motion: string; badge: string }>;
export const SHAPES: Record<MascotShape, { body: string; face: string }>;
export function resolveEmotion(value: unknown): EmotionId;
export function resolveShape(value: unknown): MascotShape;
export function renderRelaySvg(options?: MascotOptions & { standalone?: boolean; monochrome?: boolean }): string;
export function createRelayMascot(host: HTMLElement, options?: MascotOptions): MascotController;
