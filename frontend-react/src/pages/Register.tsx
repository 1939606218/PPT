import { useState } from 'react'
import { Form, Input, Button, Card, Typography, Divider, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../store/authStore'

const { Title, Text } = Typography

export default function Register() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const { data } = await authApi.register(values.username, values.password)
      setAuth(data.access_token, data.user)
      message.success('注册成功，欢迎加入！')
      navigate('/score')
    } catch (err: any) {
      message.error(err.response?.data?.detail || '注册失败，用户名已被使用')
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
      <Card style={{ width: 420, borderRadius: 16, boxShadow: '0 8px 40px rgba(0,0,0,0.10)', border: 'none' }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <img src="/logo.png" alt="BSH" style={{ height: 52, objectFit: 'contain', marginBottom: 12 }} />
          <Title level={4} style={{ margin: 0, color: '#222' }}>创建账号</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>技术演讲 AI 评分系统</Text>
        </div>

        <Divider style={{ margin: '16px 0' }} />

        <Form onFinish={onFinish} size="large" autoComplete="off">
          <Form.Item name="username" rules={[
            { required: true, message: '请输入用户名' },
            { min: 3, message: '用户名至少 3 个字符' },
          ]}>
            <Input prefix={<UserOutlined />} placeholder="用户名（至少3位）" />
          </Form.Item>
          <Form.Item name="password" rules={[
            { required: true, message: '请输入密码' },
            { min: 6, message: '密码至少 6 位' },
          ]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码（至少6位）" />
          </Form.Item>
          <Form.Item name="confirm" dependencies={['password']} rules={[
            { required: true, message: '请确认密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('password') === value) return Promise.resolve()
                return Promise.reject(new Error('两次密码不一致'))
              },
            }),
          ]}>
            <Input.Password prefix={<LockOutlined />} placeholder="确认密码" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block loading={loading}
              style={{ height: 42 }}>
              注 册
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center' }}>
          <Text type="secondary">已有账号？</Text>{' '}
          <Link to="/login">立即登录</Link>
        </div>
      </Card>
    </div>
  )
}
