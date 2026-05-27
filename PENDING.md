# Itens Pendentes (Backlog de Melhorias)

Este arquivo registra melhorias e refatorações planejadas para o futuro no projeto Risos.

## Autenticação

### [ ] Migrar autenticação JWT para Cookies HttpOnly (Bead: `risos-rih`)
- **Problema:** A autenticação atual com JWT exige que o token seja mantido em memória no frontend (Alpine.js) para evitar exposição a ataques XSS no `localStorage`. No entanto, isso faz com que a sessão do usuário seja perdida sempre que a página é recarregada (F5/refresh). Além disso, a validação de logout exige consultas recorrentes ao banco de dados (`token_blacklist`), tornando o processo essencialmente *stateful*.
- **Solução proposta:**
  - Substituir o uso de JWT em memória por cookies de sessão assinados pelo FastAPI e marcados como `HttpOnly`, `Secure` e `SameSite=Lax`.
  - O navegador gerenciará automaticamente o envio e expiração do cookie.
  - O JavaScript do frontend não terá acesso direto ao cookie, garantindo imunidade a roubos de sessão via ataques XSS.
  - Simplificar as rotas de autenticação removendo a lógica complexa de codificação/decodificação de JWTs no cliente.
