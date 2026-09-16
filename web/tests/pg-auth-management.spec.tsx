import { render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useAuthStatus } from '@/hooks/useAuthStatus';
import * as auth from '@/lib/auth';

function ManagementEntry() {
  const status=useAuthStatus();
  return status.loading ? <span>loading</span> : status.isAdmin ? <a href='/admin/users'>账户管理</a> : <span>无管理权限</span>;
}

it('tenant_admin 的实际管理权限显示入口，不要求旧 admin 字面', async () => {
  vi.spyOn(auth,'fetchAuthStatus').mockResolvedValue({enabled:true,authenticated:true,role:'tenant_admin',is_admin:true});
  render(<ManagementEntry/>);
  expect(await screen.findByRole('link',{name:'账户管理'})).toHaveAttribute('href','/admin/users');
});

it('撤销权限后不因旧 admin claim 显示入口', async () => {
  vi.spyOn(auth,'fetchAuthStatus').mockResolvedValue({enabled:true,authenticated:true,role:'admin',is_admin:false});
  render(<ManagementEntry/>);
  await waitFor(()=>expect(screen.getByText('无管理权限')).toBeInTheDocument());
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
