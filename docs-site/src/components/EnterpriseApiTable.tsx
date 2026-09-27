import React from 'react';
import Link from '@docusaurus/Link';
import routes from '../data/enterprise-routes.json';

const credential: Record<string, string> = {
  none: '无需会话',
  dt_token: 'dt_token',
  eduplus2_user_jwt: 'EduPlus2 用户 JWT',
};

/** 表格只消费经过验证的第三方接口目录。 */
export default function EnterpriseApiTable(): React.ReactElement {
  return (
    <div className="api-table-wrap">
      <table className="api-table">
        <thead>
          <tr><th>方法</th><th>路径</th><th>凭证／条件</th><th>用途</th></tr>
        </thead>
        <tbody>
          {routes.map((route) => (
            <tr key={`${route.method} ${route.path}`}>
              <td><span className={`api-method api-method--${route.method.toLowerCase()}`}>{route.method}</span></td>
              <td><Link to={`/${route.doc}/`}><code>{route.path}</code></Link></td>
              <td>{credential[route.credential] ?? route.credential}</td>
              <td>{route.summary}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
