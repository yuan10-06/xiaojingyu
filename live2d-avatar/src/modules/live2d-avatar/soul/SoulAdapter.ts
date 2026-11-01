export type DayPhase = 'dawn' | 'day' | 'dusk' | 'night';

export interface StateFrame {
  affect: {
    arousal: number;
    valence: number;
    tension: number;
    affinity: number;
  };
  residue: { emotion: string; intensity: number; decay: number }[];
  relation: { closeness: number; power: number; trust: number };
  event?: { type: string; impact: number; tag: string[] };
  memoryCue?: { id: string; salience: number; text?: string };
  gaze: { target: 'user' | 'away' | 'space'; hold: number };
  time: { hour: number; dayPhase: DayPhase };
}

export interface SoulAdapter {
  onStateFrame(cb: (frame: StateFrame) => void): void;
  onSpeak(cb: (speak: { text: string; phoneme?: string[]; volume: number }) => void): void;
  onMemoryRecall(cb: (memory: NonNullable<StateFrame['memoryCue']>) => void): void;
  sendUserInput(text: string, meta?: Record<string, unknown>): void;
  dispose(): void;
}
