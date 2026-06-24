import { useEffect, useState } from 'react'
import {
  Table, Space, Typography, Switch,
  message, Select, Popconfirm, Avatar,
} from 'antd'
import { UserOutlined, CrownOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { listUsers, updateUser } from '../../api/admin'
import type { User } from '../../types'

const { Title, Text } = Typography

export default function UserManagement() {
  const [users, setUsers]   = useState<User[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try { setUsers(await listUsers()) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const toggle = async (id: string, field: 'is_active' | 'role', value: boolean | string) => {
    try {
      await updateUser(id, { [field]: value })
      // updateUser returns {status, user_id} — update local state directly
      setUsers(u => u.map(x => x.id === id ? { ...x, [field]: value } : x))
      message.success('已更新')
    } catch {
      message.error('操作失败')
    }
  }

  const columns: ColumnsType<User> = [
    {
      title: '用户', render: (_: any, row: User) => (
        <Space>
          <Avatar icon={<UserOutlined />}
            style={{ background: row.role === 'admin' ? '#E2001A' : '#52c41a' }} />
          <div>
            <div><Text strong>{row.username}</Text></div>
            <div><Text type="secondary" style={{ fontSize: 12 }}>{row.role === 'admin' ? '管理员' : '普通用户'}</Text></div>
          </div>
        </Space>
      ),
    },
    {
      title: '角色', dataIndex: 'role', width: 160,
      render: (v: string, row: User) => (
        <Select value={v} size="small" style={{ width: 110 }}
          onChange={(val) => toggle(row.id, 'role', val)}
          options={[
            { value: 'user', label: <><UserOutlined /> 普通用户</> },
            { value: 'admin', label: <><CrownOutlined style={{ color: '#E2001A' }} /> 管理员</> },
          ]} />
      ),
    },
    {
      title: '状态', dataIndex: 'is_active', width: 120,
      render: (v: boolean, row: User) => (
        <Popconfirm
          title={v ? '确定禁用该用户？' : '确定启用该用户？'}
          onConfirm={() => toggle(row.id, 'is_active', !v)}
          okText="确定" cancelText="取消"
          okButtonProps={{ danger: v }}>
          <Switch checked={v} checkedChildren="启用" unCheckedChildren="禁用" size="small" />
        </Popconfirm>
      ),
    },
    {
      title: '注册时间', dataIndex: 'created_at', width: 165,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
      sorter: (a, b) => new Date(a.created_at!).getTime() - new Date(b.created_at!).getTime(),
      defaultSortOrder: 'descend',
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>
        <UserOutlined style={{ marginRight: 8 }} /> 用户管理
      </Title>
      <Table rowKey="id" columns={columns} dataSource={users} loading={loading}
        pagination={{ pageSize: 20, showTotal: t => `共 ${t} 名用户` }} />
    </div>
  )
}
