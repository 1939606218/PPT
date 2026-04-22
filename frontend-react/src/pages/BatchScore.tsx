import { useState, useCallback, useEffect } from 'react'
import {
  Card, Button, Upload, Typography, Space, Tag, Progress,
  Table, Tooltip, message, Divider, Row, Col, Alert,
} from 'antd'
import type { ReactNode } from 'react'
import {
  FilePdfOutlined, AudioOutlined, TrophyOutlined, DownloadOutlined,
  DeleteOutlined, PlayCircleOutlined, PlusOutlined, LoadingOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  LinkOutlined, FileExcelOutlined,
} from '@ant-design/icons'
import * as XLSX from 'xlsx'
import client from '../api/client'
import { useBatchStore } from '../store/batchStore'
import type { BatchTask, ScoreData, TaskStatus } from '../store/batchStore'

const { Title, Text } = Typography

interface PollData {
  running: boolean
  percent: number
  message: string
  step: number
}

let _sse: EventSource | null = null
let _abortFlag = false
let _wakeLock: WakeLockSentinel | null = null

function genId() {
  return Math.random().toString(36).slice(2)
}

const STATUS_TAG: Record<TaskStatus, ReactNode> = {
  waiting: <Tag icon={<ClockCircleOutlined />}  color="default">等待中</Tag>,
  running: <Tag icon={<LoadingOutlined spin />}  color="processing">评分中</Tag>,
  done:    <Tag icon={<CheckCircleOutlined />}   color="success">完成</Tag>,
  error:   <Tag icon={<CloseCircleOutlined />}   color="error">失败</Tag>,
}

export default function BatchScore() {
  // ── 配对暂存区（先选好一对，再加入队列）───────────────────────────────────
  const [stagePdf,   setStagePdf]   = useState<File | null>(null)
  const [stageAudio, setStageAudio] = useState<File | null>(null)

  // ── 任务队列（全局 store，切换路由后不丢失）──────────────────────────────
  const { tasks, running, setTasks, setRunning } = useBatchStore()

  // 页面由隐藏切回可见时，若批量任务仍在运行，重新申请 Wake Lock
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'visible' && running && !_wakeLock) {
        navigator.wakeLock?.request('screen')
          .then((lock) => { _wakeLock = lock })
          .catch(() => {})
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [running])

  // ── 将暂存区配对加入队列 ──────────────────────────────────────────────────
  const addPair = () => {
    if (!stagePdf) { message.warning('请先选择 PPT / PDF 文件'); return }
    setTasks((prev) => [
      ...prev,
      { id: genId(), pptFile: stagePdf, audioFile: stageAudio, status: 'waiting' },
    ])
    setStagePdf(null)
    setStageAudio(null)
    message.success(`已加入：${stagePdf.name}${stageAudio ? ' + ' + stageAudio.name : '（纯PPT）'}`)
  }

  const removeTask = (taskId: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId))
  }

  // ── 执行单个任务 ──────────────────────────────────────────────────────────
  const runTask = useCallback((task: BatchTask): Promise<void> => {
    return new Promise((resolve) => {
      setTasks((prev) =>
        prev.map((t) =>
          t.id === task.id ? { ...t, status: 'running', percent: 0, message: '准备中...' } : t
        )
      )

      let seenRunning = false
      let settled = false  // 防止 SSE 和 POST 双重触发

      const ts = new Date()
        .toLocaleDateString('zh-CN', { year: '2-digit', month: '2-digit', day: '2-digit' })
        .replace(/\//g, '')

      // 完成处理（成功/失败）——只执行一次
      const finish = async (success: boolean, blobUrl?: string) => {
        if (settled) return
        settled = true
        if (_sse) { _sse.close(); _sse = null }
        clearTimeout(safetyTimer)

        if (success) {
          let scoreData: ScoreData | undefined
          try {
            const jr = await client.get<ScoreData>('/last-result')
            scoreData = jr.data
          } catch { /* ignore */ }

          // 优先使用 POST 返回的 blob，否则从 /api/last-report-pdf 单独下载
          let reportUrl = blobUrl
          const reportName = `评分报告_${task.pptFile.name}_${ts}.pdf`
          if (!reportUrl) {
            try {
              const pdfRes = await client.get('/last-report-pdf', { responseType: 'blob' })
              reportUrl = URL.createObjectURL(new Blob([pdfRes.data], { type: 'application/pdf' }))
            } catch { /* 下载失败不影响主流程，只是没有下载链接 */ }
          }

          setTasks((prev) =>
            prev.map((t) =>
              t.id === task.id
                ? { ...t, status: 'done', reportUrl, reportName, percent: 100, message: '✅ 完成', scoreData }
                : t
            )
          )
        } else {
          setTasks((prev) =>
            prev.map((t) =>
              t.id === task.id
                ? { ...t, status: 'error', error: '评分失败，请重试', percent: 0 }
                : t
            )
          )
        }
        resolve()
      }

      // 安全超时 20 分钟（兜底，防止 SSE 和 POST 都静默失败）
      const safetyTimer = setTimeout(() => {
        finish(false)
      }, 20 * 60 * 1000)

      if (_sse) { _sse.close(); _sse = null }
      _sse = new EventSource('/api/progress/stream')
      _sse.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as PollData
          if (data.running) seenRunning = true
          if (seenRunning) {
            setTasks((prev) =>
              prev.map((t) =>
                t.id === task.id ? { ...t, percent: data.percent, message: data.message } : t
              )
            )
          }
          // SSE 作为任务完成的权威信号：后端明确结束后才判断成败
          if (seenRunning && !data.running) {
            if (data.percent >= 100) {
              finish(true)   // SSE 确认成功 → 用 /last-report-pdf 下载
            } else {
              finish(false)  // 后端报错
            }
          }
        } catch { /* ignore */ }
      }
      _sse.onerror = () => { /* browser auto-reconnects */ }

      // 使用该任务自己的 pptFile + audioFile，严格一一对应
      const form = new FormData()
      form.append('pdf_file', task.pptFile)
      if (task.audioFile) form.append('audio_file', task.audioFile)

      client
        .post('/analyze', form, { responseType: 'blob', timeout: 1200_000 /* 20 min */ })
        .then((res) => {
          // POST 成功：用 blob 作为 PDF 下载链接（比再 GET 一次快）
          const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
          finish(true, url)
        })
        .catch(() => {
          // POST 连接被防火墙断开是常见情况，不在此处标错
          // 让 SSE 判断真正的任务成败（后端已缓存进度状态）
          // 如果 SSE 也沉默超过 20 分钟，safetyTimer 会兜底
        })
    })
  }, [])

  // ── 批量启动 ──────────────────────────────────────────────────────────────
  const startBatch = async () => {
    const pending = tasks.filter((t) => t.status === 'waiting')
    if (pending.length === 0) { message.warning('没有待处理的任务'); return }

    // 申请 Wake Lock，阻止系统息屏/睡眠，防止批量任务中断
    try {
      _wakeLock = await navigator.wakeLock?.request('screen')
    } catch {
      // 不支持或用户拒绝，不影响主流程，仅提示
      message.warning('无法阻止息屏，建议保持屏幕常亮以防任务中断', 5)
    }

    _abortFlag = false
    setRunning(true)
    for (const task of pending) {
      if (_abortFlag) break
      await runTask(task)
    }
    setRunning(false)

    // 释放 Wake Lock
    try { await _wakeLock?.release() } catch { /* ignore */ }
    _wakeLock = null

    message.success('批量评分全部完成！')
  }

  const stopBatch = () => {
    _abortFlag = true
    setRunning(false)
    if (_sse) { _sse.close(); _sse = null }
    // 释放 Wake Lock
    _wakeLock?.release().catch(() => {})
    _wakeLock = null
    message.info('已暂停，当前任务完成后停止')
  }

  const clearDone = () => setTasks((prev) => prev.filter((t) => t.status !== 'done'))

  // ── 导出 Excel ────────────────────────────────────────────────────────────
  const exportExcel = () => {
    const doneTasks = tasks.filter((t) => t.status === 'done' && t.scoreData)
    if (doneTasks.length === 0) { message.warning('暂无已完成的评分数据'); return }

    // 子维度中文名映射
    const SUB_LABELS: Record<string, string> = {
      background_and_pain_points: '背景与痛点铺垫',
      solution_deduction:         '方案推演的连贯性',
      closed_loop_results:        '结果的闭环交代',
      universal_value:            '通用价值提炼',
      data_and_evidence:          '客观数据与证据支撑',
      business_relevance:         '业务相关性与深度',
      clarity_for_non_experts:    '跨界理解友好度',
      engineering_decision:       '工程决策与系统思维',
    }

    const rows = doneTasks.map((t, idx) => {
      const s = t.scoreData!
      const dimA = s.scores?.narrative_setup
      const dimB = s.scores?.solution_results
      const dimC = s.scores?.elevation_fluency

      const subA = dimA?.sub_dimensions ?? {}
      const subB = dimB?.sub_dimensions ?? {}

      const row: Record<string, string | number> = {
        '序号': idx + 1,
        'PPT 文件': t.pptFile.name,
        '配对音频': t.audioFile?.name ?? '—（纯PPT）',
        'PPT 类型': s.ppt_type?.type_name ?? '',
        '总分': s.total_score ?? '',
        '等级': s.grade ?? '',
        // 维度 A
        '维度A 结构与逻辑': dimA?.score ?? '',
      }
      // 维度 A 子维度
      for (const [key, label] of Object.entries({
        background_and_pain_points: SUB_LABELS.background_and_pain_points,
        solution_deduction:         SUB_LABELS.solution_deduction,
        closed_loop_results:        SUB_LABELS.closed_loop_results,
        universal_value:            SUB_LABELS.universal_value,
      })) {
        const sub = subA[key]
        row[`A-${label}`] = sub?.score ?? ''
      }
      // 维度 B
      row['维度B 内容与价值'] = dimB?.score ?? ''
      for (const [key, label] of Object.entries({
        data_and_evidence:       SUB_LABELS.data_and_evidence,
        business_relevance:      SUB_LABELS.business_relevance,
        clarity_for_non_experts: SUB_LABELS.clarity_for_non_experts,
        engineering_decision:    SUB_LABELS.engineering_decision,
      })) {
        const sub = subB[key]
        row[`B-${label}`] = sub?.score ?? ''
      }
      // 维度 C（有音频时才有）
      row['维度C 语言与呈现'] = dimC ? (dimC.score ?? '') : '—'
      return row
    })

    const ws = XLSX.utils.json_to_sheet(rows)

    // ── 列宽自适应 ──
    const colWidths = Object.keys(rows[0] ?? {}).map((key) => ({
      wch: Math.max(key.length * 2, 14),
    }))
    ws['!cols'] = colWidths

    // ── 冻结首行 ──
    ws['!freeze'] = { xSplit: 0, ySplit: 1 }

    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, '批量评分结果')

    const now = new Date()
    const ts = now.toLocaleDateString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
    }).replace(/\//g, '') +
      '_' +
      now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
        .replace(/:/g, '')
    XLSX.writeFile(wb, `批量评分结果_${ts}.xlsx`)
    message.success('Excel 已下载')
  }

  const counts = {
    total:   tasks.length,
    waiting: tasks.filter((t) => t.status === 'waiting').length,
    done:    tasks.filter((t) => t.status === 'done').length,
    error:   tasks.filter((t) => t.status === 'error').length,
  }

  const columns = [
    {
      title: '#',
      width: 44,
      render: (_: unknown, __: BatchTask, idx: number) => (
        <Text type="secondary" style={{ fontSize: 12 }}>{idx + 1}</Text>
      ),
    },
    {
      title: 'PPT 文件',
      render: (_: unknown, t: BatchTask) => (
        <Space size={4}>
          <FilePdfOutlined style={{ color: '#E2001A' }} />
          <Text style={{ fontSize: 13 }} ellipsis={{ tooltip: t.pptFile.name }}>
            {t.pptFile.name}
          </Text>
        </Space>
      ),
    },
    {
      title: '配对音频',
      width: 230,
      render: (_: unknown, t: BatchTask) =>
        t.audioFile ? (
          <Space size={4}>
            <LinkOutlined style={{ color: '#1677ff' }} />
            <Text style={{ fontSize: 12, color: '#1677ff' }} ellipsis={{ tooltip: t.audioFile.name }}>
              {t.audioFile.name}
            </Text>
          </Space>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>— 纯PPT模式</Text>
        ),
    },
    {
      title: '状态',
      width: 100,
      render: (_: unknown, t: BatchTask) => STATUS_TAG[t.status],
    },
    {
      title: '进度',
      width: 170,
      render: (_: unknown, t: BatchTask) => {
        if (t.status === 'waiting') return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>
        if (t.status === 'running') return (
          <div>
            <Progress percent={t.percent ?? 0} size="small" strokeColor="#E2001A" style={{ marginBottom: 2 }} />
            <Text type="secondary" style={{ fontSize: 11 }}>{t.message}</Text>
          </div>
        )
        if (t.status === 'done')  return <Text style={{ fontSize: 12, color: '#52c41a' }}>100%</Text>
        if (t.status === 'error') return <Text type="danger" style={{ fontSize: 12 }}>{t.error}</Text>
        return null
      },
    },
    {
      title: '操作',
      width: 110,
      render: (_: unknown, t: BatchTask) => (
        <Space>
          {t.status === 'done' && t.reportUrl && (
            <a href={t.reportUrl} download={t.reportName}>
              <Button size="small" type="primary" icon={<DownloadOutlined />}>报告</Button>
            </a>
          )}
          {(t.status === 'waiting' || t.status === 'error') && !running && (
            <Tooltip title="移除">
              <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeTask(t.id)} />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <Title level={4} style={{ marginBottom: 20 }}>
        <TrophyOutlined style={{ color: '#E2001A', marginRight: 8 }} />
        批量 PPT 评分
      </Title>

      {/* ── 第一步：配对区 ─────────────────────────────────────────────────── */}
      <Card
        style={{ borderRadius: 10, marginBottom: 16 }}
        title={<Text strong>第一步：选择文件配对，加入队列</Text>}
      >
        <Row gutter={16} align="middle">
          {/* PPT */}
          <Col xs={24} md={10}>
            <div style={{
              border: `2px dashed ${stagePdf ? '#E2001A' : '#d9d9d9'}`,
              borderRadius: 8, padding: '12px 16px',
              background: stagePdf ? '#fff1f2' : '#fafafa',
              minHeight: 76, display: 'flex', flexDirection: 'column', justifyContent: 'center',
            }}>
              <Text strong style={{ fontSize: 13 }}>
                <FilePdfOutlined style={{ color: '#E2001A', marginRight: 6 }} />
                PPT / PDF <Text type="danger">（必选）</Text>
              </Text>
              {stagePdf ? (
                <Space style={{ marginTop: 6 }} size={4}>
                  <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: stagePdf.name }}>{stagePdf.name}</Text>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />}
                    onClick={() => setStagePdf(null)} />
                </Space>
              ) : (
                <Upload accept=".pdf,.pptx,.ppt" maxCount={1} showUploadList={false}
                  beforeUpload={(f) => { setStagePdf(f); return false }}>
                  <Button size="small" icon={<PlusOutlined />} style={{ marginTop: 6 }}>选择文件</Button>
                </Upload>
              )}
            </div>
          </Col>

          {/* 连接箭头 */}
          <Col xs={0} md={1} style={{ textAlign: 'center', paddingTop: 8 }}>
            <LinkOutlined style={{ color: '#bbb', fontSize: 20 }} />
          </Col>

          {/* 音频 */}
          <Col xs={24} md={10}>
            <div style={{
              border: `2px dashed ${stageAudio ? '#1677ff' : '#d9d9d9'}`,
              borderRadius: 8, padding: '12px 16px',
              background: stageAudio ? '#f0f5ff' : '#fafafa',
              minHeight: 76, display: 'flex', flexDirection: 'column', justifyContent: 'center',
            }}>
              <Text strong style={{ fontSize: 13 }}>
                <AudioOutlined style={{ color: '#1677ff', marginRight: 6 }} />
                配对音频
                <Text type="secondary" style={{ fontWeight: 400, marginLeft: 6, fontSize: 12 }}>（可选，不传则纯PPT模式）</Text>
              </Text>
              {stageAudio ? (
                <Space style={{ marginTop: 6 }} size={4}>
                  <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: stageAudio.name }}>{stageAudio.name}</Text>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />}
                    onClick={() => setStageAudio(null)} />
                </Space>
              ) : (
                <Upload accept=".mp3,.wav,.m4a,.mp4,.mov,.ogg,.flac" maxCount={1} showUploadList={false}
                  beforeUpload={(f) => { setStageAudio(f); return false }}>
                  <Button size="small" icon={<PlusOutlined />} style={{ marginTop: 6 }}>选择音频</Button>
                </Upload>
              )}
            </div>
          </Col>

          {/* 加入按钮 */}
          <Col xs={24} md={3}>
            <Button
              type="primary" icon={<PlusOutlined />}
              onClick={addPair}
              disabled={!stagePdf || running}
              style={{ width: '100%', marginTop: 4 }}
            >
              加入队列
            </Button>
          </Col>
        </Row>

        <Divider style={{ margin: '14px 0 8px' }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          💡 每次选好一个 PPT/PDF 及其对应音频（或不选音频），点「加入队列」。每组 PDF 与音频在加入时已永久绑定，之后提交时不会与其他任务的文件混用。
        </Text>
      </Card>

      {/* ── 第二步：任务队列 ───────────────────────────────────────────────── */}
      {tasks.length > 0 && (
        <Card
          style={{ borderRadius: 10, marginBottom: 16 }}
          title={
            <Space>
              <Text strong>第二步：任务队列</Text>
              <Tag>共 {counts.total} 个</Tag>
              {counts.waiting > 0 && <Tag color="default">等待 {counts.waiting}</Tag>}
              {counts.done    > 0 && <Tag color="success">完成 {counts.done}</Tag>}
              {counts.error   > 0 && <Tag color="error">失败 {counts.error}</Tag>}
            </Space>
          }
          extra={
            counts.done > 0 && !running
              ? <Button size="small" type="text" onClick={clearDone}>清除已完成</Button>
              : null
          }
        >
          <Table
            dataSource={tasks} columns={columns} rowKey="id"
            pagination={false} size="small"
            rowClassName={(t) =>
              t.status === 'running' ? 'batch-row-running' :
              t.status === 'done'    ? 'batch-row-done'    : ''
            }
          />
        </Card>
      )}

      {tasks.length === 0 && (
        <Card style={{
          borderRadius: 10, marginBottom: 16, background: '#fafafa',
          border: '1px solid #f0f0f0', textAlign: 'center', padding: '32px 0',
        }}>
          <FilePdfOutlined style={{ fontSize: 36, color: '#ccc', display: 'block', marginBottom: 10 }} />
          <Text type="secondary">在上方选好文件配对后点「加入队列」，可多次添加</Text>
        </Card>
      )}

      {/* ── 第三步：启动 ──────────────────────────────────────────────────── */}
      <Card style={{ borderRadius: 10 }}>
        <Space size={12}>
          {!running ? (
            <Button
              type="primary" size="large" icon={<PlayCircleOutlined />}
              onClick={startBatch}
              disabled={counts.waiting === 0}
              style={{ height: 44, paddingInline: 32, fontSize: 15 }}
            >
              第三步：开始批量评分（{counts.waiting} 个待处理）
            </Button>
          ) : (
            <Button size="large" danger onClick={stopBatch}
              style={{ height: 44, paddingInline: 32, fontSize: 15 }}>
              暂停（完成当前后停止）
            </Button>
          )}
          {counts.done > 0 && (
            <Text type="secondary" style={{ fontSize: 13 }}>
              ✅ {counts.done} 个已完成，点各行「报告」下载
            </Text>
          )}
          {counts.done > 0 && (
            <Button
              icon={<FileExcelOutlined />}
              onClick={exportExcel}
              style={{ color: '#217346', borderColor: '#217346' }}
            >
              导出 Excel 汇总
            </Button>
          )}
        </Space>

        {running && (
          <>
            <Divider style={{ margin: '12px 0' }} />
            <Alert type="info" showIcon
              message="批量评分进行中，请勿关闭页面。任务按队列顺序依次处理，完成后自动开始下一个。" />
          </>
        )}
      </Card>

      <style>{`
        .batch-row-running td { background: #f6f8ff !important; }
        .batch-row-done    td { background: #f6ffed !important; }
      `}</style>
    </div>
  )
}
