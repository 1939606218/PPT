import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

interface Props {
  requireAdmin?: boolean
}

export default function ProtectedRoute({ requireAdmin = false }: Props) {
  const { token, user } = useAuthStore()
  if (!token || !user) return <Navigate to="/login" replace />
  if (requireAdmin && user.role !== 'admin') return <Navigate to="/score" replace />
  return <Outlet />
}
