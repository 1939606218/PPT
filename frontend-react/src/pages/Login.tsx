import { useState, useEffect } from 'react'
import { Form, Input, Button, Card, Typography, Divider, message, Spin, Space } from 'antd'
import { UserOutlined, LockOutlined, WifiOutlined, KeyOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../store/authStore'

const { Title, Text } = Typography

// mode:
//   'checking'  - 正在自动尝试 IP 登录（首次访问）
//   'choice'    - 退出后返回，让用户选择登录方式
//   'ipLoading' - 用户手动点击「内网IP登录」后正在请求
//   'form'      - 显示账号密码表单
type Mode = 'checking' | 'choice' | 'ipLoading' | 'form'

export default function Login() {
  const [loading, setLoading] = useState(false)
  const isAfterLogout = sessionStorage.getItem('justLoggedOut') === '1'
  const [mode, setMode] = useState<Mode>(isAfterLogout ? 'choice' : 'checking')
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  // 退出后首次渲染时清除标记
  useEffect(() => {
    if (isAfterLogout) sessionStorage.removeItem('justLoggedOut')
  }, [])

  // 首次访问自动尝试 IP 登录（退出后不自动触发）
  useEffect(() => {
    if (mode !== 'checking') return
    authApi.ipLogin()
      .then(({ data }) => {
        setAuth(data.access_token, data.user)
        message.success('内网自动登录成功')
        navigate('/score')
      })
      .catch(() => setMode('form'))
  }, [])

  const handleIpLogin = () => {
    setMode('ipLoading')
    authApi.ipLogin()
      .then(({ data }) => {
        setAuth(data.access_token, data.user)
        message.success('内网IP登录成功')
        navigate('/score')
      })
      .catch(() => {
        message.error('IP登录失败，请使用账号密码登录')
        setMode('choice')
      })
  }

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const { data } = await authApi.login(values.username, values.password)
      setAuth(data.access_token, data.user)
      message.success(`欢迎回来，${data.user.username}！`)
      navigate('/score')
    } catch (err: any) {
      message.error(err.response?.data?.detail || '登录失败，请检查用户名或密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #f5f7fa 0%, #e8edf5 100%)',
    }}>
      <Card style={{ width: 400, borderRadius: 16, boxShadow: '0 8px 40px rgba(0,0,0,0.10)', border: 'none' }}>
        {/* BSH Logo */}
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <img src="/logo.png" alt="BSH" style={{ height: 52, objectFit: 'contain', marginBottom: 12 }} />
          <Title level={4} style={{ margin: 0, color: '#222' }}>技术演讲 AI 评分系统</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>Bosch Home Appliances</Text>
        </div>

        <Divider style={{ margin: '16px 0' }} />

        {(mode === 'checking' || mode === 'ipLoading') ? (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <Spin />
            <div style={{ marginTop: 12, color: '#999', fontSize: 13 }}>
              {mode === 'checking' ? '正在检测内网环境...' : '正在通过内网IP登录...'}
            </div>
          </div>
        ) : mode === 'choice' ? (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <Button
              type="primary" block size="large" icon={<WifiOutlined />}
              style={{ height: 46 }}
              onClick={handleIpLogin}
            >
              内网 IP 免密登录
            </Button>
            <Button
              block size="large" icon={<KeyOutlined />}
              style={{ height: 46 }}
              onClick={() => setMode('form')}
            >
              账号密码登录
            </Button>
          </Space>
        ) : (
          <>
            <Form onFinish={onFinish} size="large" autoComplete="off">
              <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input prefix={<UserOutlined />} placeholder="用户名" />
              </Form.Item>
              <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                <Input.Password prefix={<LockOutlined />} placeholder="密码" />
              </Form.Item>
              <Form.Item style={{ marginBottom: 8 }}>
                <Button type="primary" htmlType="submit" block loading={loading}
                  style={{ height: 42, fontSize: 15 }}>
                  登 录
                </Button>
              </Form.Item>
            </Form>
            <div style={{ textAlign: 'center', marginBottom: 8 }}>
              <Button type="link" size="small" onClick={() => setMode('choice')}>← 返回选择登录方式</Button>
            </div>
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">还没有账号？</Text>{' '}
              <Link to="/register">立即注册</Link>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
