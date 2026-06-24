/**
 * 批量评分全局状态（内存级，不持久化到 localStorage）
 * 组件卸载/重新挂载后状态保持，刷新页面后重置。
 */
import { create } from 'zustand'

export type TaskStatus = 'waiting' | 'running' | 'done' | 'error'

export interface SubDim {
  score: number
  max_score: number
  comment?: string
}
export interface DimScore {
  score: number
  max_score: number
  sub_dimensions?: Record<string, SubDim>
}
export interface ScoreData {
  total_score: number
  grade: string
  has_audio: boolean
  ppt_type?: { type_name: string }
  scores: {
    narrative_setup?: DimScore
    solution_results?: DimScore
    elevation_fluency?: DimScore
  }
}

export interface BatchTask {
  id: string
  pptFile: File
  audioFile: File | null
  status: TaskStatus
  reportUrl?: string
  reportName?: string
  error?: string
  percent?: number
  message?: string
  scoreData?: ScoreData
}

interface BatchState {
  tasks: BatchTask[]
  running: boolean
  setTasks: (updater: BatchTask[] | ((prev: BatchTask[]) => BatchTask[])) => void
  setRunning: (v: boolean) => void
  clearAll: () => void
}

export const useBatchStore = create<BatchState>()((set) => ({
  tasks: [],
  running: false,
  setTasks: (updater) =>
    set((s) => ({
      tasks: typeof updater === 'function' ? updater(s.tasks) : updater,
    })),
  setRunning: (v) => set({ running: v }),
  clearAll: () => set({ tasks: [], running: false }),
}))
