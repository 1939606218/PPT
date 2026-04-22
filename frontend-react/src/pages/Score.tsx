import { useState, useEffect, useRef } from 'react'
import {
  Card, Button, Upload, Progress, Typography, Space,
  Alert, Row, Col, message, Steps,
} from 'antd'
import {
  FilePdfOutlined, AudioOutlined, TrophyOutlined, DownloadOutlined,
  CloudUploadOutlined, ThunderboltOutlined, RobotOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { useScoreStore } from '../store/scoreStore'

const { Title, Text } = Typography

export default function Score() {
  const [pdfFile, setPdfFile]     = useState<File | null>(null)
  const [audioFile, setAudioFile] = useState<File | null>(null)

  const {
    loading, poll, reportUrl, reportName, error,
    audioFileName, submit,
  } = useScoreStore()

  const notified = useRef({ url: reportUrl, err: error })
  useEffect(() => {
    if (reportUrl && reportUrl !== notified.current.url) {
      message.success('评分报告已生成！')
      notified.current.url = reportUrl
    }
  }, [reportUrl])
  useEffect(() => {
    if (error && error !== notified.current.err) {
      message.error(error)
      notified.current.err = error
    }
  }, [error])

  const handleSubmit = () => {
    if (!pdfFile) { message.warning('请先选择 PPT / PDF 文件'); return }
    submit(pdfFile, audioFile, null)
  }

  const stepCurrent = poll ? Math.min(poll.step, 3) : -1
  const steps = [
    { title: '上传文件',       icon: <CloudUploadOutlined /> },
    { title: '解析 PPT & 音频', icon: <ThunderboltOutlined /> },
    { title: 'AI 综合评分',    icon: <RobotOutlined /> },
    { title: '生成 PDF 报告',  icon: <FileTextOutlined /> },
  ]

  const vlText = poll && poll.vl_total > 0
    ? `📄 PPT分析：${poll.vl_current}/${poll.vl_total} 页`
    : '📄 PPT分析：准备中...'
  const hasAudio = !!audioFile || !!audioFileName
  const audioText = !hasAudio
    ? '🔇 纯PPT模式（无音频）'
    : poll?.audio_done
      ? '🎙️ 音频转录：✅ 完成'
      : poll && poll.audio_elapsed > 0
        ? `🎙️ 音频转录：进行中… ${poll.audio_elapsed}s`
        : '🎙️ 音频转录：等待中...'
  const vlPct = poll && poll.vl_total > 0
    ? Math.round(poll.vl_current / poll.vl_total * 100) : 0

  return (
    <div style={{ maxWidth: 820, margin: '0 auto' }}>
      <Title level={4} style={{ marginBottom: 20 }}>
        <TrophyOutlined style={{ color: '#E2001A', marginRight: 8 }} />
        PPT 技术演讲评分
      </Title>

      <Card style={{ borderRadius: 10, marginBottom: 20 }}>
        <Row gutter={24}>
          <Col xs={24} md={12}>
            <Text strong>📊 PPT / PDF 文件 <Text type="danger">*</Text></Text>
            <Upload accept=".pdf,.pptx,.ppt" maxCount={1}
              beforeUpload={(f) => { setPdfFile(f); return false }}
              onRemove={() => setPdfFile(null)}>
              <Button icon={<FilePdfOutlined />}
                style={{ marginTop: 8, width: '100%', textAlign: 'left' }}>
                {pdfFile ? pdfFile.name : '选择 PPT / PDF 文件'}
              </Button>
            </Upload>
          </Col>
          <Col xs={24} md={12}>
            <Text strong>🎙️ 演讲音频</Text><br />
            <Text type="secondary" style={{ fontSize: 12 }}>
              可选 · 不上传则跳过维度C，A/B各占50分
            </Text>
            <Upload accept=".mp3,.wav,.m4a,.mp4,.mov,.ogg,.flac" maxCount={1}
              beforeUpload={(f) => { setAudioFile(f); return false }}
              onRemove={() => setAudioFile(null)}>
              <Button icon={<AudioOutlined />}
                style={{ marginTop: 4, width: '100%', textAlign: 'left' }}>
                {audioFile ? audioFile.name : '选择音频 / 视频文件'}
              </Button>
            </Upload>
          </Col>
        </Row>

        <Button type="primary" size="large" block onClick={handleSubmit}
          loading={loading} disabled={!pdfFile || loading}
          style={{ marginTop: 20, height: 46, fontSize: 16, borderRadius: 8 }}>
          {loading ? '评分中...' : '🚀 开始 AI 评分'}
        </Button>
      </Card>

      {poll && (
        <Card style={{ borderRadius: 10, marginBottom: 20 }}>
          <Steps current={stepCurrent} size="small" items={steps} style={{ marginBottom: 20 }} />

          <Progress
            percent={poll.percent}
            status={poll.percent === 100 ? 'success' : 'active'}
            strokeColor={{ from: '#E2001A', to: '#ff7875' }}
          />

          <div style={{ marginTop: 10 }}>
            <Text style={{ fontSize: 13 }}>{poll.message}</Text>
          </div>

          {poll.step >= 1 && (
            <div style={{
              marginTop: 10, padding: '10px 14px', borderRadius: 8,
              background: poll.step === 1 ? '#f6f8ff' : '#f6ffed',
              border: `1px solid ${poll.step === 1 ? '#e8eeff' : '#b7eb8f'}`,
            }}>
              {poll.step === 1 ? (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <div>
                    <Text style={{ fontSize: 12 }}>{vlText}</Text>
                    {poll.vl_total > 0 && (
                      <Progress percent={vlPct} size="small" showInfo={false}
                        style={{ marginTop: 4 }} strokeColor="#E2001A" />
                    )}
                  </div>
                  <Text style={{ fontSize: 12 }}>{audioText}</Text>
                </Space>
              ) : (
                <Text style={{ fontSize: 12, color: '#52c41a' }}>
                  ✅ PPT {poll.vl_total > 0 ? `全部 ${poll.vl_total} 页` : ''}分析完成
                  {hasAudio ? '，音频转录完成' : '（纯PPT模式）'}
                </Text>
              )}
            </div>
          )}

          {poll.detail && poll.step > 1 && (
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
              {poll.detail}
            </Text>
          )}
        </Card>
      )}

      {error && <Alert message={error} type="error" style={{ marginBottom: 20 }} showIcon />}

      {reportUrl && (
        <Card style={{
          borderRadius: 10, textAlign: 'center',
          background: 'linear-gradient(135deg, #fff1f2 0%, #fff5f5 100%)',
          border: '1px solid #ffccc7',
        }}>
          <TrophyOutlined style={{ fontSize: 44, color: '#E2001A', display: 'block', marginBottom: 10 }} />
          <Title level={4} style={{ color: '#E2001A', marginBottom: 4 }}>报告已生成！</Title>
          <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
            报告已同步保存到您的历史记录
          </Text>
          <a href={reportUrl} download={reportName}>
            <Button type="primary" size="large" icon={<DownloadOutlined />}
              style={{ height: 46, borderRadius: 8, fontSize: 15, paddingInline: 32 }}>
              下载 PDF 评分报告
            </Button>
          </a>
        </Card>
      )}

      {!poll && (
        <Card size="small" style={{ borderRadius: 10, background: '#fafafa', border: '1px solid #f0f0f0' }}>
          <Text strong style={{ fontSize: 13 }}>📝 使用说明</Text>
          <ul style={{ margin: '8px 0 0 18px', fontSize: 13, color: '#666', lineHeight: 2 }}>
            <li>支持 PDF、PPTX、PPT 格式演示文件</li>
            <li>支持 MP3、WAV、M4A、MP4 等音频/视频格式</li>
            <li>有音频时：维度A+B各45分、维度C 10分，共100分</li>
            <li>纯PPT模式：维度A+B各50分，共100分</li>
          </ul>
        </Card>
      )}
    </div>
  )
}
