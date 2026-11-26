import { useAuth } from '../../contexts/AuthContext';
import { Link, useLocation } from 'react-router-dom';
import { Home, FileText, Calendar, BookOpen, LogOut, X } from 'lucide-react';
import { cn } from '../../lib/utils';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { user, logout } = useAuth();
  const location = useLocation();

  if (!user) return null;

  // Menu berdasarkan Role
  const menus = {
    ADMIN: [
      { name: 'Dashboard', path: '/admin', icon: Home },
      { name: 'Manajemen User', path: '/admin/users', icon: FileText },
    ],
    DOSEN: [
      { name: 'Dashboard', path: '/dosen', icon: Home },
      { name: 'Jadwal Bimbingan', path: '/dosen/jadwal', icon: Calendar },
    ],
    MAHASISWA: [
      { name: 'Dashboard', path: '/mahasiswa', icon: Home },
      { name: 'Pengajuan Judul', path: '/mahasiswa/judul', icon: FileText },
      { name: 'Progres Skripsi', path: '/mahasiswa/progres', icon: BookOpen },
    ],
  };

  const currentMenu = menus[user.role];

  return (
    <>
      {/* Overlay untuk Mobile (Latar gelap saat sidebar terbuka) */}
      {isOpen && (
        <div 
          className="fixed inset-0 z-40 bg-black/50 lg:hidden" 
          onClick={onClose}
        />
      )}

      {/* Sidebar Utama */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-64 transform bg-white border-r border-gray-200 transition-transform duration-300 ease-in-out lg:static lg:translate-x-0",
          isOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="flex h-16 items-center justify-between px-6 border-b border-gray-200">
          <span className="text-xl font-bold text-blue-600">SBS A4</span>
          <button onClick={onClose} className="lg:hidden text-gray-500 hover:text-gray-700">
            <X size={24} />
          </button>
        </div>

        <div className="flex flex-col h-[calc(100vh-4rem)] justify-between p-4">
          <nav className="space-y-1">
            {currentMenu.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                    isActive 
                      ? "bg-blue-50 text-blue-700" 
                      : "text-gray-700 hover:bg-gray-100"
                  )}
                >
                  <Icon size={20} />
                  {item.name}
                </Link>
              );
            })}
          </nav>

          <div className="border-t border-gray-200 pt-4">
            <div className="px-3 py-2 mb-2">
              <p className="text-sm font-medium text-gray-900">{user.name}</p>
              <p className="text-xs text-gray-500">{user.role}</p>
            </div>
            <button
              onClick={logout}
              className="flex w-full items-center gap-3 px-3 py-2 text-sm font-medium text-red-600 rounded-md hover:bg-red-50 transition-colors"
            >
              <LogOut size={20} />
              Logout
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}