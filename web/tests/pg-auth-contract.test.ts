import assert from 'node:assert/strict';
import test from 'node:test';
import * as auth from '../lib/auth';

test('账户管理由已认证后端权限字段控制，不由全局角色推断', () => {
  assert.equal(typeof auth.canManageAccounts, 'function');
  assert.equal(auth.canManageAccounts({enabled:true, authenticated:true, role:'tenant_admin', is_admin:true}), true);
  assert.equal(auth.canManageAccounts({enabled:true, authenticated:true, role:'admin', is_admin:false}), false);
  assert.equal(auth.canManageAccounts({enabled:true, authenticated:false, role:'tenant_admin', is_admin:true}), false);
});

test('新密码与 PG 12..72 UTF-8 byte 合同一致', () => {
  assert.equal(typeof auth.validAccountPassword, 'function');
  assert.equal(auth.validAccountPassword('12345678'), false);
  assert.equal(auth.validAccountPassword('中文密码'), true);
  assert.equal(auth.validAccountPassword('密'.repeat(24)), true);
  assert.equal(auth.validAccountPassword('密'.repeat(25)), false);
});
