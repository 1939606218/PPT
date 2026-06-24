import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Space, Typography, Drawer,
  Popconfirm, message, Statistic, Row, Col, Card, Tabs, Spin, Empty,
} from 'antd'
import {
  DownloadOutlined, DeleteOutlined, EyeOutlined,
  AudioOutlined, FilePdfOutlined, BulbOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { listHistory, getHistory, downloadPdf, deleteHistory, getHistoryReasoning } from '../api/history'
import type { RecordSummary, RecordDetail, DimScore, ReasoningEntry } from '../types'

const { Title, Text } = Typography

function gradeColor(grade: string) {
  const map: Record<string, string> = { S: 'gold', A: 'green', B: 'blue', C: 'orange', D: 'red' }
  return map[grade] ?? 'default'
}

const DIM_KEYS: Array<{ key: string; label: string }> = [
  { key: 'narrative_setup',   label: '维度 A · 内容逻辑与叙事' },
  { key: 'solution_results',  label: '维度 B · 解决方案清晰度' },
  { key: 'elevation_fluency', label: '维度 C · 演讲表达' },
]

const ROLE_LABEL: Record<string, string> = {
  classify:           '🗂️ 分类 LLM',
  narrative_setup:    '📖 维度 A · 结构与逻辑',
  solution_results:   '🔧 维度 B · 内容与价值',
  elevation_fluency:  '🎙️ 维度 C · 语言与呈现',
  summary:            '✍️ 汇总 LLM',
}

export default function History() {
  const [records, setRecords]     = useState<RecordSummary[]>([])
  const [loading, setLoading]     = useState(true)
  const [detail, setDetail]       = useState<RecordDetail | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  // Reasoning drawer state
  const [reasoningOpen, setReasoningOpen]     = useState(false)
  const [reasoningData, setReasoningData]     = useState<ReasoningEntry[]>([])
  const [reasoningLoading, setReasoningLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await listHistory()
      setRecords(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openDetail = async (id: string) => {
    setDrawerOpen(true); setDetailLoading(true)
    try {
      const d = await getHistory(id)
      setDetail(d)
    } finally {
      setDetailLoading(false)
    }
  }

  const openReasoning = async (id: string) => {
    setReasoningOpen(true); setReasoningLoading(true); setReasoningData([])
    try {
      const data = await getHistoryReasoning(id)
      setReasoningData(data)
    } catch {
      message.error('加载推理过程失败')
    } finally {
      setReasoningLoading(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteHistory(id)
      message.success('已删除')
      setRecords(r => r.filter(x => x.id !== id))
    } catch {
      message.error('删除失败')
    }
  }

  const columns: ColumnsType<RecordSummary> = [
    {
      title: 'PPT 文件名', dataIndex: 'filename', ellipsis: true,
      render: (v: string) => (
        <><FilePdfOutlined style={{ color: '#E2001A', marginRight: 6 }} />{v}</>
      ),
    },
    {
      title: '音频文件名', dataIndex: 'audio_filename', ellipsis: true,
      render: (v: string | null) => v
        ? <><AudioOutlined style={{ color: '#722ed1', marginRight: 6 }} />{v}</>
        : <Text type="secondary" style={{ fontSize: 12 }}>无</Text>,
    },
    {
      title: '总分', dataIndex: 'total_score', width: 90,
      render: (v: number) => <Text strong style={{ color: '#E2001A' }}>{v}</Text>,
      sorter: (a, b) => a.total_score - b.total_score,
    },
    {
      title: '等级', dataIndex: 'grade', width: 80,
      render: (v: string) => <Tag color={gradeColor(v)}>{v} 级</Tag>,
    },
    {
      title: '音频', dataIndex: 'has_audio', width: 90,
      render: (v: boolean) => v
        ? <Tag icon={<AudioOutlined />} color="purple">有音频</Tag>
        : <Tag>纯 PPT</Tag>,
    },
    {
      title: '评分时间', dataIndex: 'created_at', width: 170,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
      sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      defaultSortOrder: 'descend',
    },
    {
      title: '操作', width: 200, fixed: 'right',
      render: (_: any, row: RecordSummary) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(row.id)}>详情</Button>
          {row.has_pdf && (
            <Button size="small" icon={<DownloadOutlined />} type="link"
              onClick={() => downloadPdf(row.id, row.filename)}>PDF</Button>
          )}
          <Button size="small" icon={<BulbOutlined />} type="link"
            style={{ color: '#722ed1' }}
            onClick={() => openReasoning(row.id)}>推理</Button>
          <Popconfirm title="确定删除该记录？" onConfirm={() => handleDelete(row.id)}
            okText="删除" cancelText="取消" okButtonProps={{ danger: true }}>
            <Button size="small" icon={<DeleteOutlined />} danger type="text" />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>📋 我的评分历史</Title>

      <Table
        rowKey="id" columns={columns} dataSource={records} loading={loading}
        scroll={{ x: 780 }} pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }}
      />

      <Drawer title="评分详情" open={drawerOpen} width={560}
        onClose={() => { setDrawerOpen(false); setDetail(null) }}
        loading={detailLoading}>
        {detail && (
          <>
            {/* 总分卡片行 */}
            <Row gutter={16} style={{ marginBottom: 20 }}>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center', borderRadius: 8 }}>
                  <Statistic title="总分" value={detail.total_score}
                    valueStyle={{ color: '#E2001A', fontSize: 30, fontWeight: 700 }} />
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center', borderRadius: 8 }}>
                  <Statistic title="等级" formatter={() =>
                    <Tag color={gradeColor(detail.grade)}
                      style={{ fontSize: 18, padding: '2px 10px' }}>{detail.grade}</Tag>} />
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center', borderRadius: 8 }}>
                  <Statistic title="模式" formatter={() =>
                    detail.has_audio
                      ? <Tag icon={<AudioOutlined />} color="purple">有音频</Tag>
                      : <Tag>纯 PPT</Tag>} />
                </Card>
              </Col>
            </Row>

            {/* 维度明细 */}
            {DIM_KEYS.map(({ key, label }) => {
              const d: DimScore | undefined = detail.score_data?.scores?.[key]
              if (!d) return null
              const subDims = Object.values(d.sub_dimensions ?? {})
              return (
                <Card key={key} size="small" style={{ marginBottom: 12, borderRadius: 8 }}
                  title={
                    <span>
                      <Text strong>{label}</Text>
                      <Text style={{ float: 'right', color: '#E2001A', fontWeight: 700 }}>
                        {d.score} / {d.max_score}
                      </Text>
                    </span>
                  }>
                  {subDims.map((s, i) => (
                    <div key={i}
                      style={{ marginBottom: 4, display: 'flex', justifyContent: 'space-between' }}>
                      <Text style={{ fontSize: 12 }}>子维度 {i + 1}</Text>
                      <Text style={{ fontSize: 12 }}>{s.score} / {s.max_score}</Text>
                    </div>
                  ))}
                  {d.comment && (
                    <div style={{ marginTop: 8, padding: '6px 8px', background: '#fafafa',
                      borderRadius: 6, fontSize: 12, color: '#555', lineHeight: 1.6 }}>
                      {d.comment}
                    </div>
                  )}
                </Card>
              )
            })}

            {/* 综合总结 */}
            {detail.score_data?.summary && (
              <Card size="small" style={{ borderRadius: 8 }} title="🎯 综合总结">
                <Text style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                  {detail.score_data.summary}
                </Text>
              </Card>
            )}
          </>
        )}
      </Drawer>

      {/* 推理过程 Drawer */}
      <Drawer
        title={<><BulbOutlined style={{ color: '#722ed1', marginRight: 8 }} />AI 推理过程</>}
        open={reasoningOpen}
        width={680}
        onClose={() => { setReasoningOpen(false); setReasoningData([]) }}
      >
        {reasoningLoading ? (
          <Spin style={{ display: 'block', marginTop: 60 }} />
        ) : reasoningData.length === 0 ? (
          <Empty
            description="暂无推理记录（请在 Admin → LLM 设置中开启思考模式后重新评分）"
            style={{ marginTop: 60 }}
          />
        ) : (
          <Tabs
            tabPosition="left"
            type="card"
            style={{ height: 'calc(100vh - 120px)' }}
            tabBarStyle={{ width: 160, whiteSpace: 'normal', lineHeight: '1.4' }}
            items={reasoningData.map(entry => ({
              key: entry.role,
              label: <span style={{ fontSize: 12 }}>{ROLE_LABEL[entry.role] ?? entry.role}</span>,
              children: (
                <div style={{
                  height: 'calc(100vh - 140px)',
                  overflowY: 'auto',
                  background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 8,
                  padding: '12px 16px',
                  fontSize: 13, lineHeight: 1.8, whiteSpace: 'pre-wrap', color: '#333',
                }}>
                  {entry.reasoning_text}
                </div>
              ),
            }))}
          />
        )}
      </Drawer>
    </div>
  )
}
