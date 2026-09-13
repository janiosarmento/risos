# Handoff: Risos — Redesenho em Material 3

## Visão geral
Redesenho visual da interface do Risos (leitor de RSS com resumos por IA), reorganizando a hierarquia de informação sem alterar a arquitetura de dados/API. Duas linhas de exploração foram produzidas — Nocturne (dark, mono-accent) e Material 3 (claro/escuro, azul padrão Google) — a direção final escolhida foi **Material 3**.

## Sobre os arquivos de design
Os arquivos `.dc.html` neste pacote são **referências de design em HTML** — protótipos de alta fidelidade mostrando aparência e comportamento pretendidos, não código de produção para copiar diretamente. A tarefa é **recriar esses designs no ambiente real do Risos** (Alpine.js + Tailwind no frontend, FastAPI no backend) usando os padrões já estabelecidos no repo (`htdocs/static/js/components/*.js`, `htdocs/static/locales/*.json`, os mixins Alpine existentes) — não substituir a stack.

## Fidelidade
**Alta fidelidade (hifi)** para cor, tipografia, espaçamento e raio de borda (tokens Material 3 documentados abaixo). As interações (clique, hover, drag-and-drop de tags entre tópicos, teclas de atalho J/K/Enter/etc.) são as já existentes no app real — os protótipos não reimplementam JS, apenas mostram os estados visuais.

## Ponto de partida obrigatório: o código real
Antes de implementar, leia o próprio repositório do Risos incluído em `uploads/risos/` (ou o repo do usuário, se conectado):
- `htdocs/static/js/components/settings.js`, `curation.js`, `postDetail.js` — comportamento real de cada tela
- `htdocs/static/locales/pt-BR.json` e `en-US.json` — toda a cópia de UI deve vir daqui, nunca inventada
- `backend/app/routes/preferences.py` — confirma que a chave de IA é referenciada por **nome de segredo no Jano** (`jano_secret_name`), nunca armazenada em texto puro; a UI de Configurações > IA deve refletir isso (campo "Nome do segredo no Jano" + indicador de segredo encontrado/não encontrado, nunca um input de senha)
- `backend/prompts.yaml` / `PROMPTS.md` — prompts editáveis nas Configurações > IA

**Peça ao Claude Code para criticar esta entrega**: comparar tela a tela contra os componentes Alpine reais e apontar qualquer funcionalidade do app (ex.: drag-and-drop de tags entre tópicos, sugestão de tópicos por IA, exportação Mímir, reset do circuit breaker, regeneração de resumo Shift+R) que os mockups não cobriram, antes de começar a implementar.

## Telas incluídas (Risos Redesign (Material).dc.html)
| ID | Tela | Notas |
|----|------|-------|
| 2a/2b | Lista de posts (claro/escuro) | Sidebar com filtros, tópicos, categorias/feeds; lista com score de sugestão e termo bloqueado |
| 2c/2d | Post aberto (claro/escuro) | Resumo IA em painel tonal cheio (`--md-primary-container`) à esquerda, original à direita |
| 2e | Curadoria IA | Badges essencial/redundante/não classificado — vocabulário exato do `curation.js` |
| 2f | Configurações — aba IA | Campo "Nome do segredo no Jano", circuit breaker, sliders |
| 2g | Mobile — lista e post | Bottom nav de 4 itens + painel de resumo |
| 2h/2i | Sugeridos + perfil de tags | Slider de sensibilidade, tags do perfil (roxa=perfil, riscada=ignorada) |
| 2j | OPML — importar/exportar | Upload, resultado da importação, export Mímir |
| 2k | Estados vazios/erro | Tudo lido, sem feeds, segredo não encontrado, busca sem resultado |

## Design tokens (Material 3, baseline azul do Google)
Ver `Risos Design Handoff.dc.html` (incluído neste pacote) para a folha de especificação completa: cores (claro/escuro), tipografia (Google Sans + Roboto), raios (8/16/28px), elevação (2 níveis de sombra), anatomia de cada componente (botão preenchido/outlined, FAB, item de lista, chip, switch, painel de resumo IA).

## Regra de segurança — não negociável
Nunca implementar um campo de "API key" em texto ou input de senha nas Configurações. O único campo é o nome do segredo (`jano_secret_name`), resolvido em tempo de execução pelo backend contra um allowlist. Ver `backend/app/routes/preferences.py::_validate_jano_secret`.

## Arquivos deste pacote
- `Risos Redesign (Material).dc.html` — todas as telas (2a–2k), claro e escuro
- `Risos Design Handoff.dc.html` — specs de tokens e componentes
- `Risos Redesign.dc.html` — exploração alternativa em Nocturne (dark, mono-accent) — referência, não a direção escolhida
- Este README
