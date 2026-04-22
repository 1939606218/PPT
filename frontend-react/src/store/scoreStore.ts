import { create } from 'zustand'
import client from '../api/client'

export interface PollData {
  running: boolean
  percent: number
  message: string
  detail: string
  step: number
  vl_current: number
  vl_total: number
  audio_done: boolean
  audio_elapsed: number
}

interface ScoreState {
  loading: boolean
  poll: PollData | null
  reportUrl: string | null
  reportName: string
  error: string | null
  pdfFileName: string
  audioFileName: string

  submit: (pdfFile: File, audioFile: File | null, token: string | null) => void
  reset: () => void
}

// Module-level SSE ref — survives component unmount
let _sse: EventSource | null = null

export const useScoreStore = create<ScoreState>()((set) => ({
  loading: false,
  poll: null,
  reportUrl: null,
  reportName: '',
  error: null,
  pdfFileName: '',
  audioFileName: '',

  submit: (pdfFile, audioFile, _token) => {
    // 先释放旧的 blob URL，再重置状态
    const prev = useScoreStore.getState()
    if (prev.reportUrl) URL.revokeObjectURL(prev.reportUrl)

    // Stop any existing SSE
    if (_sse) { _sse.close(); _sse = null }

    set({
      loading: true,
      error: null,
      reportUrl: null,
      reportName: '',
      pdfFileName: pdfFile.name,
      audioFileName: audioFile?.name ?? '',
      poll: {
        running: true, percent: 0, message: '准备中...', detail: '',
        step: 0, vl_current: 0, vl_total: 0, audio_done: false, audio_elapsed: 0,
      },
    })

    // Start SSE — 必须先见到 running=True 才更新 UI，防止旧数据干扰
    let seenRunning = false
    _sse = new EventSource('/api/progress/stream')
    _sse.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as PollData
        if (data.running) seenRunning = true
        if (seenRunning) set({ poll: data })
        if (seenRunning && !data.running && data.percent >= 100) {
          _sse?.close(); _sse = null
        }
      } catch { /* ignore */ }
    }
    _sse.onerror = () => { /* browser auto-reconnects; ignore */ }

    // Fire the analyze request (runs independently of component lifecycle)
    const form = new FormData()
    form.append('pdf_file', pdfFile)
    if (audioFile) form.append('audio_file', audioFile)

    client.post('/analyze', form, { responseType: 'blob', timeout: 600_000 })
      .then((res) => {
        const ts = new Date().toLocaleDateString('zh-CN', { year:'2-digit', month:'2-digit', day:'2-digit' }).replace(/\//g, '')
        const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
        const name = `评分报告_${pdfFile.name}_${ts}.pdf`
        set((s) => ({
          reportUrl: url,
          reportName: name,
          poll: s.poll ? { ...s.poll, percent: 100, running: false, step: 3, message: '✅ 完成！' } : s.poll,
        }))
      })
      .catch((err: any) => {
        const msg = err.response ? '服务器处理失败，请稍后重试' : '请求超时或网络异常'
        set({ error: msg })
      })
      .finally(() => {
        set({ loading: false })
        if (_sse) { _sse.close(); _sse = null }
      })
  },

  reset: () => {
    if (_sse) { _sse.close(); _sse = null }
    set({
      loading: false, poll: null, reportUrl: null, reportName: '',
      error: null, pdfFileName: '', audioFileName: '',
    })
  },
}))
