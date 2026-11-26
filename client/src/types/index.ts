export type UserRole = 'ADMIN' | 'DOSEN' | 'MAHASISWA';

export interface User {
  id: string;
  name: string;
  role: UserRole;
}