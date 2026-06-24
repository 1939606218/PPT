import { useState } from 'react'
import { Layout, Menu, Avatar, Dropdown, Space, Typography, Button, Tag } from 'antd'
import {
  DesktopOutlined, HistoryOutlined, SettingOutlined,
  TeamOutlined, FileTextOutlined, LogoutOutlined, UserOutlined, RobotOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

const { Header, Sider, Content } = Layout
const { Text } = Typography

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()

  const isAdmin = user?.role === 'admin'

  const menuItems = [
    { key: '/score',   icon: <DesktopOutlined />,        label: 'PPT 评分' },

    { key: '/history', icon: <HistoryOutlined />,         label: '我的历史' },
    ...(isAdmin ? [
      { type: 'divider' as const },
      { key: 'admin', icon: <SettingOutlined />, label: 'Admin 管理', children: [
        { key: '/admin/history', icon: <FileTextOutlined />, label: '全量历史' },
        { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
        { key: '/batch',   icon: <UnorderedListOutlined />,   label: '批量评分' },
        { key: '/admin/prompts', icon: <FileTextOutlined />, label: '提示词编辑' },
        { key: '/admin/llm-settings', icon: <RobotOutlined />, label: 'LLM 设置' },
        { key: '/admin/scoring-config', icon: <SettingOutlined />, label: '评分配置' },
      ]},
    ] : []),
  ]

  const userMenu = {
    items: [
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'logout') {
        sessionStorage.setItem('justLoggedOut', '1')
        logout()
        navigate('/login')
      }
    },
  }

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f7fa' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}
        width={200}
        style={{ background: '#fff', boxShadow: '2px 0 8px rgba(0,0,0,0.06)' }}>

        {/* Logo 区域 */}
        <div style={{
          height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center',
          borderBottom: '1px solid #f5f5f5', padding: '0 12px', overflow: 'hidden',
        }}>
          {collapsed ? (
            <img src="/logo.png" alt="BSH" style={{ height: 28, objectFit: 'contain' }} />
          ) : (
            <img src="/logo.png" alt="BSH" style={{ height: 36, objectFit: 'contain', maxWidth: '100%' }} />
          )}
        </div>

        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={isAdmin ? ['admin'] : []}
          items={menuItems}
          onClick={({ key }) => { if (!key.startsWith('admin')) navigate(key) }}
          style={{ borderRight: 0, marginTop: 8 }}
        />
      </Sider>

      <Layout style={{ background: '#f5f7fa' }}>
        <Header style={{
          background: '#fff', padding: '0 24px', display: 'flex',
          alignItems: 'center', justifyContent: 'space-between',
          borderBottom: '1px solid #f0f0f0', height: 56, boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
        }}>
          <Text type="secondary" style={{ fontSize: 13 }}>
            技术演讲 AI 评分系统
          </Text>
          <Dropdown menu={userMenu} placement="bottomRight">
            <Button type="text" style={{ height: 40 }}>
              <Space>
                <Avatar size={28} icon={<UserOutlined />}
                  style={{ background: '#E2001A' }} />
                <Text strong>{user?.username}</Text>
                {isAdmin && (
                  <Tag color="red" style={{ margin: 0, fontSize: 11 }}>Admin</Tag>
                )}
              </Space>
            </Button>
          </Dropdown>
        </Header>

        <Content style={{ margin: 24, minHeight: 'calc(100vh - 56px - 48px)' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
