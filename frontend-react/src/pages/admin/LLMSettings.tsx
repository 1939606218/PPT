import { useEffect, useState } from 'react'
import {
  Card, Select, Switch, Button, Space, Typography, message, Spin, Alert,
} from 'antd'
import { SaveOutlined, RobotOutlined } from '@ant-design/icons'
import { getLLMSettings, updateLLMSettings } from '../../api/admin'

const { Title, Text } = Typography

const MODELS = [
  { value: 'qwen3-max', label: 'qwen3-max（支持思考模式）' },
  { value: 'qwen-long', label: 'qwen-long（不支持思考模式）' },
]

export default function LLMSettings() {
  const [loading, setLoading]               = useState(true)
  const [saving, setSaving]                 = useState(false)
  const [model, setModel]                   = useState('qwen3-max')
  const [enableThinking, setEnableThinking] = useState(false)

  const supportsThinking = model.startsWith('qwen3')

  useEffect(() => {
    getLLMSettings()
      .then(s => {
        setModel(s.model)
        setEnableThinking(s.enable_thinking)
      })
      .finally(() => setLoading(false))
  }, [])

  const handleModelChange = (val: string) => {
    setModel(val)
    if (!val.startsWith('qwen3')) setEnableThinking(false)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateLLMSettings({ model, enable_thinking: enableThinking })
      message.success('LLM 设置已保存')
    } catch {
      message.error('保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spin style={{ display: 'block', marginTop: 80 }} />

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 24 }}>
        <RobotOutlined style={{ marginRight: 8 }} />
        LLM 模型设置
      </Title>

      <Card style={{ maxWidth: 520 }}>
        <Space direction="vertical" size={24} style={{ width: '100%' }}>

          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>评分模型</Text>
            <Select
              value={model}
              onChange={handleModelChange}
              options={MODELS}
              style={{ width: '100%' }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <Text strong>启用思考模式（enable_thinking）</Text>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {supportsThinking
                  ? '开启后 AI 会在回答前进行深度推理，评分更准确，但耗时更长'
                  : '当前模型不支持思考模式，请切换到 qwen3-max'}
              </Text>
            </div>
            <Switch
              checked={enableThinking}
              onChange={setEnableThinking}
              disabled={!supportsThinking}
            />
          </div>

          {enableThinking && supportsThinking && (
            <Alert
              type="info"
              showIcon
              message="思考模式已开启"
              description="AI 将输出 reasoning_content 推理过程（记录在服务器日志），最终评分结果不变。"
            />
          )}

          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={handleSave}
            block
          >
            保 存
          </Button>

        </Space>
      </Card>
    </div>
  )
}
