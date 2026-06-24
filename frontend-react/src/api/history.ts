import client from './client'
import type { RecordSummary, RecordDetail, ReasoningEntry } from '../types'

export const historyApi = {
  list: () => client.get<RecordSummary[]>('/history'),
  get: (id: string) => client.get<RecordDetail>(`/history/${id}`),
  downloadPdfUrl: (id: string) => `/api/history/${id}/pdf`,
  delete: (id: string) => client.delete(`/history/${id}`),
}

// Named exports for direct import in pages
export const listHistory  = async (): Promise<RecordSummary[]> =>
  (await client.get<RecordSummary[]>('/history')).data

export const getHistory   = async (id: string): Promise<RecordDetail> =>
  (await client.get<RecordDetail>(`/history/${id}`)).data

export const downloadPdfUrl = (id: string): string => `/api/history/${id}/pdf`

export const deleteHistory = async (id: string): Promise<void> => {
  await client.delete(`/history/${id}`)
}

export const getHistoryReasoning = async (id: string): Promise<ReasoningEntry[]> =>
  (await client.get<ReasoningEntry[]>(`/history/${id}/reasoning`)).data

/** 下载 PDF（带 Auth header，避免 401） */
export const downloadPdf = async (id: string, filename: string): Promise<void> => {
  const res = await client.get(`/history/${id}/pdf`, { responseType: 'blob' })
  const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}_评分报告.pdf`
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url) }, 500)
}
