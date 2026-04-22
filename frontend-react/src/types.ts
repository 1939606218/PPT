// 全局类型定义

export interface User {
  id: string
  username: string
  role: 'user' | 'admin'
  is_active: boolean
  created_at: string
}

export interface TokenOut {
  access_token: string
  token_type: string
  user: User
}

export interface RecordSummary {
  id: string
  filename: string
  audio_filename?: string | null
  has_audio: boolean
  total_score: number
  grade: string
  has_pdf: boolean
  created_at: string
}

export interface RecordDetail extends RecordSummary {
  score_data: ScoringResult
}

export interface ScoringResult {
  has_audio: boolean
  ppt_type: { type_key: string; type_name: string; reasoning: string }
  scores: Record<string, DimScore>
  total_score: number
  grade: string
  strengths: string[]
  weaknesses: string[]
  suggestions: string[]
  summary: string
}

export interface DimScore {
  score: number
  max_score: number
  comment: string
  content_relevance?: string
  relevance_reason?: string
  sub_dimensions?: Record<string, SubDimScore>
}

export interface SubDimScore {
  score: number
  max_score: number
  comment: string
}

export interface ReasoningEntry {
  role: string
  reasoning_text: string
}

export interface RecordWithUser extends RecordSummary {
  user_id: string
  username: string
}

export interface PromptItem {
  key: string      // filled in by frontend from Record key
  label: string
  content: string
}

// types.ts 中新增
export interface DeviceTokenOut extends TokenOut {
  device_id: string;
}