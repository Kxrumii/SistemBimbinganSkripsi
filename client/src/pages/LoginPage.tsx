import { useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { GraduationCap, User, Lock, Eye, EyeOff, ArrowRight, BookOpen } from 'lucide-react';
import { cn } from '../lib/utils';

export function LoginPage() {
  const navigate = useNavigate();
  const { login, user } = useAuth();
  
  const [activeRole, setActiveRole] = useState<'MAHASISWA' | 'DOSEN'>('MAHASISWA');
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  if (user) {
    return <Navigate to="/app/dashboard" replace />;
  }

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    setTimeout(() => {
      login(activeRole);
      setIsLoading(false);
      navigate('/app/dashboard');
    }, 1000);
  };

  return (
    <div className="h-screen w-full overflow-hidden bg-canvas flex items-center justify-center p-4 sm:p-8 lg:p-12">
      
      <div className="w-full max-w-[1050px] h-full max-h-[680px] bg-surface relative overflow-hidden rounded-[2.5rem] shadow-[0_25px_60px_-15px_rgba(20,69,54,0.15)] border border-border-subtle flex">
        
        {/* ========================================================
            FORM DOSEN (Berada di KIRI)
            ======================================================== */}
        <div 
          className={cn(
            "absolute inset-y-0 left-0 w-full lg:w-1/2 flex flex-col justify-center p-8 sm:p-12 transition-all duration-700",
            activeRole === 'DOSEN' ? "opacity-100 z-10" : "opacity-0 z-0 pointer-events-none"
          )}
        >
          <div className="w-full max-w-sm mx-auto space-y-6">
            <div className="text-center lg:text-left space-y-2">
              <div className="flex items-center justify-center lg:justify-start gap-2 text-primary mb-2">
                <BookOpen size={28} />
                <span className="font-bold text-xl text-ink font-heading">SBS</span>
              </div>
              <h2 className="text-3xl font-bold text-ink font-heading">Login Dosen</h2>
              <p className="text-slate-muted text-sm">Masuk untuk membimbing mahasiswa.</p>
            </div>

            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-ink">NIDN / Email</label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-muted">
                    <User size={18} />
                  </div>
                  <input type="text" required placeholder="197804152003121002" className="w-full pl-10 pr-4 py-3 bg-surface-muted border border-border-subtle rounded-xl text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all" />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-ink">Kata Sandi</label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-muted">
                    <Lock size={18} />
                  </div>
                  <input type={showPassword ? "text" : "password"} required placeholder="••••••••" className="w-full pl-10 pr-10 py-3 bg-surface-muted border border-border-subtle rounded-xl text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all" />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-muted hover:text-ink transition-colors">
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              <button type="submit" disabled={isLoading} className="w-full mt-2 bg-primary hover:bg-primary-hover text-white font-semibold py-3.5 rounded-xl shadow-md transition-all flex items-center justify-center gap-2 group disabled:opacity-70">
                {isLoading && activeRole === 'DOSEN' ? (
                  <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <>Masuk Dosen <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" /></>
                )}
              </button>
            </form>
          </div>
        </div>

        {/* ========================================================
            FORM MAHASISWA (Berada di KANAN)
            ======================================================== */}
        <div 
          className={cn(
            "absolute inset-y-0 right-0 w-full lg:w-1/2 flex flex-col justify-center p-8 sm:p-12 transition-all duration-700",
            activeRole === 'MAHASISWA' ? "opacity-100 z-10" : "opacity-0 z-0 pointer-events-none"
          )}
        >
          <div className="w-full max-w-sm mx-auto space-y-6">
            <div className="text-center lg:text-left space-y-2">
              <div className="flex items-center justify-center lg:justify-start gap-2 text-primary mb-2">
                <BookOpen size={28} />
                <span className="font-bold text-xl text-ink font-heading">SBS</span>
              </div>
              <h2 className="text-3xl font-bold text-ink font-heading">Login Mahasiswa</h2>
              <p className="text-slate-muted text-sm">Pantau progres skripsi dan revisi Anda.</p>
            </div>

            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-ink">NIM / Email</label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-muted">
                    <User size={18} />
                  </div>
                  <input type="text" required placeholder="1247050031" className="w-full pl-10 pr-4 py-3 bg-surface-muted border border-border-subtle rounded-xl text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all" />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-semibold text-ink">Kata Sandi</label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-muted">
                    <Lock size={18} />
                  </div>
                  <input type={showPassword ? "text" : "password"} required placeholder="••••••••" className="w-full pl-10 pr-10 py-3 bg-surface-muted border border-border-subtle rounded-xl text-sm text-ink focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all" />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-muted hover:text-ink transition-colors">
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              <button type="submit" disabled={isLoading} className="w-full mt-2 bg-primary hover:bg-primary-hover text-white font-semibold py-3.5 rounded-xl shadow-md transition-all flex items-center justify-center gap-2 group disabled:opacity-70">
                {isLoading && activeRole === 'MAHASISWA' ? (
                  <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <>Masuk Mahasiswa <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" /></>
                )}
              </button>
            </form>
          </div>
        </div>

        {/* ========================================================
            THE SLIDING OVERLAY (Persegi Hijau Melayang)
            ======================================================== */}
        <div 
          className={cn(
            "absolute inset-y-0 w-full lg:w-1/2 z-20 flex flex-col justify-center items-center p-10 bg-gradient-to-br from-primary via-primary-hover to-tertiary text-white",
            "transition-all duration-700 ease-[cubic-bezier(0.68,-0.55,0.27,1.55)]", 
            activeRole === 'MAHASISWA' 
              ? "translate-x-0 lg:rounded-r-[4rem] translate-y-0" 
              : "translate-x-full lg:rounded-l-[4rem] lg:rounded-r-none translate-y-0"
          )}
        >
          {/* Ornamen Latar */}
          <div className="absolute top-10 left-10 opacity-10 pointer-events-none">
            <GraduationCap size={140} />
          </div>

          <div className="relative z-20 text-center space-y-6 max-w-sm">
            <h1 className="text-3xl lg:text-4xl font-bold tracking-tight text-white transition-opacity duration-700">
              {activeRole === 'MAHASISWA' ? 'Hello, Mahasiswa!' : 'Hello, Dosen!'}
            </h1>
            <p className="text-white/80 font-medium transition-opacity duration-700">
              {activeRole === 'MAHASISWA' 
                ? 'Masuk untuk memantau progres skripsi dan catatan revisi Anda.' 
                : 'Masuk untuk membimbing, memberikan catatan, dan menyetujui revisi.'}
            </p>
            
            {/* Tombol Geser Overlay */}
            <div className="pt-8">
              <button
                onClick={() => setActiveRole(activeRole === 'MAHASISWA' ? 'DOSEN' : 'MAHASISWA')}
                className="px-6 py-2.5 rounded-full border-2 border-white text-white font-semibold text-sm hover:bg-white hover:text-primary transition-colors duration-300 shadow-lg"
              >
                Masuk sebagai {activeRole === 'MAHASISWA' ? 'Dosen' : 'Mahasiswa'}
              </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}