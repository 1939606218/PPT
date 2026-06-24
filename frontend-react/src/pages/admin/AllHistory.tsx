import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Space, Typography, Drawer,
  Row, Col, Card, Statistic, Select, Input,
} from 'antd'
import { EyeOutlined, DownloadOutlined, AudioOutlined, SearchOutlined, FilePdfOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { allHistory } from '../../api/admin'
import { getHistory, downloadPdf } from '../../api/history'
import type { RecordWithUser, RecordDetail, DimScore } from '../../types'

const { Title, Text } = Typography

function gradeColor(grade: string) {
  const map: Record<string, string> = { S: 'gold', A: 'green', B: 'blue', C: 'orange', D: 'red' }
  return map[grade] ?? 'default'
}

const DIM_KEYS: Array<{ key: string; label: string }> = [
  { key: 'narrative_setup',   label: '维度 A · 内容逻辑' },
  { key: 'solution_results',  label: '维度 B · 解决方案' },
  { key: 'elevation_fluency', label: '维度 C · 演讲表达' },
]

export default function AllHistory() {
  const [records, setRecords]       = useState<RecordWithUser[]>([])
  const [filtered, setFiltered]     = useState<RecordWithUser[]>([])
  const [loading, setLoading]       = useState(true)
  const [search, setSearch]         = useState('')
  const [gradeFilter, setGradeFilter] = useState<string | null>(null)
  const [detail, setDetail]         = useState<RecordDetail | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await allHistory()
      setRecords(data); setFiltered(data)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    let r = records
    if (search)      r = r.filter(x => x.filename.includes(search) || x.username.includes(search))
    if (gradeFilter) r = r.filter(x => x.grade === gradeFilter)
    setFiltered(r)
  }, [search, gradeFilter, records])

  const openDetail = async (id: string) => {
    setDrawerOpen(true); setDetailLoading(true)
    try { setDetail(await getHistory(id)) }
    finally { setDetailLoading(false) }
  }

  const columns: ColumnsType<RecordWithUser> = [
    { title: '用户', dataIndex: 'username', width: 110,
      render: (v: string) => <Tag color="geekblue">{v}</Tag> },
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
      render: (v: string) => <Tag color={gradeColor(v)}>{v}</Tag>,
    },
    {
      title: '音频', dataIndex: 'has_audio', width: 90,
      render: (v: boolean) => v
        ? <Tag icon={<AudioOutlined />} color="purple">有</Tag>
        : <Tag>无</Tag>,
    },
    {
      title: '时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
      sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      defaultSortOrder: 'descend',
    },
    {
      title: '操作', width: 130, fixed: 'right',
      render: (_: any, row: RecordWithUser) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(row.id)}>详情</Button>
          {row.has_pdf && (
            <Button size="small" icon={<DownloadOutlined />} type="link"
              onClick={() => downloadPdf(row.id, row.filename)}>PDF</Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>🗂️ 全部评分记录（管理员）</Title>

      <Space style={{ marginBottom: 16 }}>
        <Input placeholder="搜索文件名/用户" prefix={<SearchOutlined />}
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ width: 220 }} allowClear />
        <Select placeholder="等级筛选" allowClear style={{ width: 120 }}
          onChange={v => setGradeFilter(v ?? null)}
          options={['S','A','B','C','D'].map(g => ({ value: g, label: `${g} 级` }))} />
        <Button onClick={load}>刷新</Button>
        <Text type="secondary">{filtered.length} / {records.length} 条</Text>
      </Space>

      <Table rowKey="id" columns={columns} dataSource={filtered} loading={loading}
        scroll={{ x: 880 }} pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }} />

      <Drawer title="评分详情" open={drawerOpen} width={560}
        onClose={() => { setDrawerOpen(false); setDetail(null) }}
        loading={detailLoading}>
        {detail && (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center', borderRadius: 8 }}>
                  <Statistic title="总分" value={detail.total_score}
                    valueStyle={{ color: '#E2001A', fontWeight: 700 }} />
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center', borderRadius: 8 }}>
                  <Statistic title="等级" formatter={() =>
                    <Tag color={gradeColor(detail.grade)} style={{ fontSize: 16 }}>{detail.grade}</Tag>} />
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" style={{ textAlign: 'center', borderRadius: 8 }}>
                  <Statistic title="模式" formatter={() =>
                    detail.has_audio
                      ? <Tag icon={<AudioOutlined />} color="purple">有音频</Tag>
                      : <Tag>纯PPT</Tag>} />
                </Card>
              </Col>
            </Row>

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
                      borderRadius: 6, fontSize: 12, color: '#555' }}>
                      {d.comment}
                    </div>
                  )}
                </Card>
              )
            })}

            {detail.score_data?.summary && (
              <Card size="small" style={{ borderRadius: 8 }} title="综合总结">
                <Text style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>
                  {detail.score_data.summary}
                </Text>
              </Card>
            )}
          </>
        )}
      </Drawer>
    </div>
  )
}
