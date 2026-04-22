import client from './client'
import type { RecordWithUser, PromptItem, User } from '../types'

export type LLMSettingsData = { model: string; enable_thinking: boolean }

export const adminApi = {
  allHistory:    () => client.get<RecordWithUser[]>('/admin/history'),
  listUsers:     () => client.get<User[]>('/admin/users'),
  updateUser:    (id: string, data: { is_active?: boolean; role?: string }) =>
    client.patch<{ status: string }>(`/admin/users/${id}`, data),
  getPrompts:    () => client.get<Record<string, Omit<PromptItem, 'key'>>>('/admin/prompts'),
  updatePrompt:  (key: string, content: string) =>
    client.put<{ status: string; key: string }>(`/admin/prompts/${key}`, { content }),
  restorePrompt: (key: string) =>
    client.post<{ status: string; key: string; content: string }>(`/admin/prompts/${key}/restore`),
}

// Named exports for direct import in pages
export const allHistory = async (): Promise<RecordWithUser[]> =>
  (await client.get<RecordWithUser[]>('/admin/history')).data

export const listUsers = async (): Promise<User[]> =>
  (await client.get<User[]>('/admin/users')).data

export const updateUser = async (
  id: string,
  data: { is_active?: boolean; role?: string },
): Promise<{ status: string }> =>
  (await client.patch<{ status: string }>(`/admin/users/${id}`, data)).data

export const getPrompts = async (): Promise<PromptItem[]> => {
  const res = await client.get<Record<string, Omit<PromptItem, 'key'>>>('/admin/prompts')
  return Object.entries(res.data).map(([key, val]) => ({ key, ...val }))
}

export const updatePrompt = async (key: string, content: string): Promise<{ status: string; key: string }> =>
  (await client.put<{ status: string; key: string }>(`/admin/prompts/${key}`, { content })).data

export const restorePrompt = async (key: string): Promise<{ key: string; content: string }> => {
  const res = await client.post<{ status: string; key: string; content: string }>(
    `/admin/prompts/${key}/restore`
  )
  return res.data
}

export const getLLMSettings = async (): Promise<LLMSettingsData> =>
  (await client.get<LLMSettingsData>('/admin/llm-settings')).data

export const updateLLMSettings = async (settings: LLMSettingsData): Promise<{ status: string }> =>
  (await client.put<{ status: string }>('/admin/llm-settings', settings)).data

export type ScoringConfigData = {
  with_audio: Record<string, { label: string; max_score: number }>
  no_audio:   Record<string, { label: string; max_score: number }>
  sub_dimensions: Record<string, { labels: string[]; ratio: number[] }>
  relevance:  { low_cap_pct: number; mid_cap_pct: number; low_threshold: number; high_threshold: number }
  prompt_files: Record<string, string>
}

export const getScoringConfig = async (): Promise<ScoringConfigData> =>
  (await client.get<ScoringConfigData>('/admin/scoring-config')).data

export const updateScoringConfig = async (cfg: ScoringConfigData): Promise<{ status: string }> =>
  (await client.put<{ status: string }>('/admin/scoring-config', cfg)).data
