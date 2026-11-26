import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { LoginPage } from './pages/LoginPage';
import { MainLayout } from './components/layout/MainLayout';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function DashboardPlaceholder({ title }: { title: string }) {
  const { logout } = useAuth();
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-ink font-heading">{title}</h1>
      <p className="text-carbon">Halaman ini masih dalam tahap pengembangan.</p>
      <button onClick={logout} className="px-4 py-2 bg-error/10 text-error rounded-md">Logout</button>
    </div>
  );
}

function AppRoutes() {
  return (
    <Routes>
      {/* 1. Rute Utama langsung mengarahkan ke /login */}
      <Route path="/" element={<Navigate to="/login" replace />} />
      
      {/* 2. Halaman Login */}
      <Route path="/login" element={<LoginPage />} />

      {/* 3. Halaman Terproteksi */}
      <Route 
        path="/app" 
        element={
          <ProtectedRoute>
            <MainLayout />
          </ProtectedRoute>
        }
      >
        <Route path="dashboard" element={<DashboardPlaceholder title="Dashboard" />} />
        <Route path="dosen" element={<DashboardPlaceholder title="Dashboard Dosen" />} />
        <Route path="mahasiswa" element={<DashboardPlaceholder title="Dashboard Mahasiswa" />} />
      </Route>

      {/* 4. Fallback jika rute tidak ditemukan */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;