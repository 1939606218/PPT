import { useEffect, useState } from 'react'
import {
  Tabs, Button, Space, Typography, message,
  Spin, Alert, Tooltip,
} from 'antd'
import { SaveOutlined, UndoOutlined, EditOutlined } from '@ant-design/icons'
import { getPrompts, updatePrompt, restorePrompt } from '../../api/admin'
import type { PromptItem } from '../../types'

const { Title, Text } = Typography

const PROMPT_ORDER = ['classify', 'dimA', 'dimB', 'dimC', 'summary']
const PROMPT_ICONS: Record<string, string> = {
  classify: '🗂️',
  dimA:     '📖',
  dimB:     '🔧',
  dimC:     '🎙️',
  summary:  '✍️',
}

export default function PromptEditor() {
  const [prompts, setPrompts]       = useState<PromptItem[]>([])
  const [loading, setLoading]       = useState(true)
  const [saving, setSaving]         = useState<string | null>(null)
  const [restoring, setRestoring]   = useState<string | null>(null)
  const [drafts, setDrafts]         = useState<Record<string, string>>({})
  const [activeKey, setActiveKey]   = useState('classify')

  const load = async () => {
    setLoading(true)
    try {
      const data = await getPrompts()                   // returns PromptItem[]
      setPrompts(data)
      const d: Record<string, string> = {}
      data.forEach(p => { d[p.key] = p.content })
      setDrafts(d)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const getContent = (key: string) =>
    prompts.find(p => p.key === key)?.content ?? ''

  const isDirty = (key: string) => drafts[key] !== getContent(key)

  const handleSave = async (key: string) => {
    setSaving(key)
    try {
      await updatePrompt(key, drafts[key])
      setPrompts(ps => ps.map(p => p.key === key ? { ...p, content: drafts[key] } : p))
      message.success('Prompt 已保存')
    } catch { message.error('保存失败') }
    finally { setSaving(null) }
  }

  const handleRestore = async (key: string) => {
    setRestoring(key)
    try {
      const res = await restorePrompt(key)
      setPrompts(ps => ps.map(p => p.key === key ? { ...p, content: res.content } : p))
      setDrafts(d => ({ ...d, [key]: res.content }))
      message.success('已恢复默认值')
    } catch { message.error('恢复失败') }
    finally { setRestoring(null) }
  }

  // sort by defined order
  const sortedPrompts = [...prompts].sort(
    (a, b) => (PROMPT_ORDER.indexOf(a.key) ?? 99) - (PROMPT_ORDER.indexOf(b.key) ?? 99)
  )

  const items = sortedPrompts.map(p => ({
    key: p.key,
    label: (
      <span>
        {PROMPT_ICONS[p.key] ?? '📝'} {p.label}
        {isDirty(p.key) && (
          <EditOutlined style={{ marginLeft: 4, color: '#fa8c16', fontSize: 11 }} />
        )}
      </span>
    ),
    children: (
      <div style={{ paddingTop: 8 }}>
        {isDirty(p.key) && (
          <Alert message="有未保存的修改" type="warning" banner
            style={{ marginBottom: 8, fontSize: 12 }} />
        )}

        <textarea
          value={drafts[p.key] ?? ''}
          onChange={e => setDrafts(d => ({ ...d, [p.key]: e.target.value }))}
          rows={28}
          style={{
            width: '100%', fontFamily: 'monospace', fontSize: 13,
            border: '1px solid #d9d9d9', borderRadius: 8, padding: 12,
            resize: 'vertical', outline: 'none', lineHeight: 1.6,
            background: isDirty(p.key) ? '#fffbe6' : '#fff',
          }}
        />

        <Space style={{ marginTop: 12 }}>
          <Button type="primary" icon={<SaveOutlined />}
            loading={saving === p.key}
            disabled={!isDirty(p.key)}
            onClick={() => handleSave(p.key)}>
            保存
          </Button>
          <Tooltip title="恢复为系统内置默认 Prompt（不可撤销）">
            <Button icon={<UndoOutlined />}
              loading={restoring === p.key}
              onClick={() => handleRestore(p.key)}>
              恢复默认
            </Button>
          </Tooltip>
          {isDirty(p.key) && (
            <Button type="text"
              onClick={() => setDrafts(d => ({ ...d, [p.key]: getContent(p.key) }))}>
              放弃修改
            </Button>
          )}
        </Space>
      </div>
    ),
  }))

  if (loading) return <div style={{ textAlign: 'center', paddingTop: 60 }}><Spin size="large" /></div>

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>⚙️ Prompt 编辑器</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        修改各 LLM 的提示词后点击「保存」立即生效；「恢复默认」将覆盖为 .default.md 文件的内容。
      </Text>
      <Tabs activeKey={activeKey} onChange={setActiveKey} items={items} type="card"
        style={{ background: '#fff', padding: '12px 16px', borderRadius: 10 }} />
    </div>
  )
}

