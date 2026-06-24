import { useEffect, useState } from 'react'
import {
  Card, InputNumber, Button, Typography, message, Spin,
  Divider, Row, Col, Tag, Tooltip,
} from 'antd'
import { SaveOutlined, PercentageOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { getScoringConfig, updateScoringConfig } from '../../api/admin'
import type { ScoringConfigData } from '../../api/admin'

const { Title, Text } = Typography

const DIM_ORDER_AUDIO    = ['narrative_setup', 'solution_results', 'elevation_fluency']
const DIM_ORDER_NO_AUDIO = ['narrative_setup', 'solution_results']

function totalScore(dims: Record<string, { max_score: number }>) {
  return Object.values(dims).reduce((s, d) => s + (d.max_score ?? 0), 0)
}

export default function ScoringConfig() {
  const [loading, setLoading] = useState(true)
  const [saving,  setSaving]  = useState(false)
  const [cfg, setCfg]         = useState<ScoringConfigData | null>(null)

  useEffect(() => {
    getScoringConfig()
      .then(setCfg)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin style={{ display: 'block', marginTop: 80 }} />
  if (!cfg)    return null

  const waTotal = totalScore(cfg.with_audio)
  const naTotal = totalScore(cfg.no_audio)

  const setDimScore = (mode: 'with_audio' | 'no_audio', key: string, val: number) => {
    setCfg(prev => {
      if (!prev) return prev
      return {
        ...prev,
        [mode]: { ...prev[mode], [key]: { ...prev[mode][key], max_score: val } },
      }
    })
  }

  const setRelevance = (field: keyof ScoringConfigData['relevance'], val: number) => {
    setCfg(prev => prev ? { ...prev, relevance: { ...prev.relevance, [field]: val } } : prev)
  }

  const setSubDimRatio = (dimKey: string, idx: number, val: number) => {
    setCfg(prev => {
      if (!prev) return prev
      const existing = prev.sub_dimensions[dimKey]
      if (!existing) return prev
      const r = [...existing.ratio]
      r[idx] = val
      return {
        ...prev,
        sub_dimensions: {
          ...prev.sub_dimensions,
          [dimKey]: { ...existing, ratio: r },
        },
      }
    })
  }

  const handleSave = async () => {
    if (!cfg) return
    setSaving(true)
    try {
      await updateScoringConfig(cfg)
      message.success('评分配置已保存，下次评分立即生效')
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? '保存失败，请检查各项合计是否为100分')
    } finally {
      setSaving(false)
    }
  }

  const DimTable = ({
    mode, order,
  }: {
    mode: 'with_audio' | 'no_audio'
    order: string[]
  }) => {
    const total = totalScore(cfg[mode])
    return (
      <>
        {order.map(key => {
          const dim = cfg[mode][key]
          if (!dim) return null
          return (
            <Row key={key} align="middle" gutter={12} style={{ marginBottom: 12 }}>
              <Col span={14}>
                <Text>{dim.label}</Text>
              </Col>
              <Col span={6}>
                <InputNumber
                  min={1} max={99} step={1}
                  value={dim.max_score}
                  onChange={v => setDimScore(mode, key, v ?? 1)}
                  addonAfter="分"
                  style={{ width: '100%' }}
                />
              </Col>
            </Row>
          )
        })}
        <Divider dashed style={{ margin: '8px 0' }} />
        <Row>
          <Col span={14}><Text strong>合计</Text></Col>
          <Col span={6}>
            <Tag color={total === 100 ? 'success' : 'error'} style={{ fontSize: 14 }}>
              {total} / 100
            </Tag>
          </Col>
        </Row>
      </>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 24 }}>
        ⚖️ 评分维度配置
      </Title>

      <Row gutter={24}>
        {/* 有音频 */}
        <Col span={12}>
          <Card
            title={<><Tag color="purple">有音频模式</Tag> A + B + C = 100 分</>}
            size="small" style={{ borderRadius: 8 }}
          >
            <DimTable mode="with_audio" order={DIM_ORDER_AUDIO} />
          </Card>
        </Col>

        {/* 无音频 */}
        <Col span={12}>
          <Card
            title={<><Tag color="blue">无音频 / 纯PPT 模式</Tag> A + B = 100 分</>}
            size="small" style={{ borderRadius: 8 }}
          >
            <DimTable mode="no_audio" order={DIM_ORDER_NO_AUDIO} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 24 }}>
        {/* 相关性限制 */}
        <Col span={8}>
          <Card
            title={
              <span>
                📊 内容相关性封顶比例
                <Tooltip title="演讲与PPT相关性判定后，低/中相关的总分上限百分比">
                  <InfoCircleOutlined style={{ marginLeft: 6, color: '#999' }} />
                </Tooltip>
              </span>
            }
            size="small" style={{ borderRadius: 8 }}
          >
            {[
              { field: 'low_cap_pct'  as const, label: '🔴 低相关 — 总分上限' },
              { field: 'mid_cap_pct'  as const, label: '🟡 中相关 — 总分上限' },
            ].map(({ field, label }) => (
              <Row key={field} align="middle" gutter={12} style={{ marginBottom: 12 }}>
                <Col span={14}><Text>{label}</Text></Col>
                <Col span={10}>
                  <InputNumber
                    min={0.05} max={0.99} step={0.05}
                    value={cfg.relevance[field]}
                    formatter={v => `${Math.round(Number(v) * 100)}`}
                    parser={v => Number(v) / 100}
                    onChange={v => setRelevance(field, v ?? cfg.relevance[field])}
                    addonAfter={<PercentageOutlined />}
                    style={{ width: '100%' }}
                  />
                </Col>
              </Row>
            ))}
          </Card>
        </Col>

        {/* 维度A 子维度权重 */}
        <Col span={8}>
          <Card
            title={
              <span>
                🔢 维度A 子维度权重
                <Tooltip title="各子维度相对权重，系统按比例缩放到满分，无需合计等于100">
                  <InfoCircleOutlined style={{ marginLeft: 6, color: '#999' }} />
                </Tooltip>
              </span>
            }
            size="small" style={{ borderRadius: 8 }}
          >
            {(cfg.sub_dimensions?.narrative_setup?.labels ?? []).map((label, i) => (
              <Row key={i} align="middle" gutter={12} style={{ marginBottom: 12 }}>
                <Col span={16}><Text style={{ fontSize: 12 }}>{label}</Text></Col>
                <Col span={8}>
                  <InputNumber
                    min={1} max={99} step={1}
                    value={cfg.sub_dimensions?.narrative_setup?.ratio?.[i] ?? 11}
                    onChange={v => setSubDimRatio('narrative_setup', i, v ?? 1)}
                    style={{ width: '100%' }}
                  />
                </Col>
              </Row>
            ))}
          </Card>
        </Col>

        {/* 维度B 子维度权重 */}
        <Col span={8}>
          <Card
            title={
              <span>
                🔢 维度B 子维度权重
                <Tooltip title="各子维度相对权重，系统按比例缩放到满分，无需合计等于100">
                  <InfoCircleOutlined style={{ marginLeft: 6, color: '#999' }} />
                </Tooltip>
              </span>
            }
            size="small" style={{ borderRadius: 8 }}
          >
            {(cfg.sub_dimensions?.solution_results?.labels ?? []).map((label, i) => (
              <Row key={i} align="middle" gutter={12} style={{ marginBottom: 12 }}>
                <Col span={16}><Text style={{ fontSize: 12 }}>{label}</Text></Col>
                <Col span={8}>
                  <InputNumber
                    min={1} max={99} step={1}
                    value={cfg.sub_dimensions?.solution_results?.ratio?.[i] ?? 11}
                    onChange={v => setSubDimRatio('solution_results', i, v ?? 1)}
                    style={{ width: '100%' }}
                  />
                </Col>
              </Row>
            ))}
          </Card>
        </Col>
      </Row>

      <div style={{ marginTop: 24 }}>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          onClick={handleSave}
          disabled={waTotal !== 100 || naTotal !== 100}
        >
          保存配置
        </Button>
        {(waTotal !== 100 || naTotal !== 100) && (
          <Text type="danger" style={{ marginLeft: 12 }}>
            各模式维度分数合计必须恰好等于 100 分才能保存
          </Text>
        )}
      </div>
    </div>
  )
}
