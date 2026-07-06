// Shared types for API responses

export interface QueueItem {
  title: string;
  status: string;
  quality: string;
  size_mb: number;
  sizeleft_mb: number;
  progress: number;
  timeleft: string;
  eta: string;
  warning: boolean;
}

export interface SabnzbdSlot {
  filename: string;
  category: string;
  status: string;
  size_mb: number;
  sizeleft_mb: number;
  progress: number;
  timeleft: string;
}

export type SabnzbdData = {
  status: string;
  paused: boolean;
  speed: string;
  speed_limit: string;
  disk_free: string;
  slots: SabnzbdSlot[];
  total_count: number;
}

export interface QueueResponse {
  timestamp: number;
  sonarr: QueueItem[];
  radarr: QueueItem[];
  sabnzbd: SabnzbdData | null;
}

export interface ServiceStatus {
  name: string;
  status: string;
  shows?: number;
  movies?: number;
  libraries?: number;
  issues?: number;
  speed?: string;
  queue_count?: number;
  paused?: boolean;
}

export interface StatusResponse {
  timestamp: number;
  services: Record<string, ServiceStatus>;
  overall: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}
