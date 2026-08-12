# Sistema de Controle de Embalagem de Ataduras

Sistema simples com login, controle de entradas/saídas de fardos e dashboard financeiro.

## Como rodar (passo a passo)

1. **Instale o Python** (se ainda não tiver): https://www.python.org/downloads/ (marque "Add Python to PATH" na instalação, no Windows).

2. **Abra o terminal / prompt de comando** dentro da pasta do projeto (`sistema_ataduras`).

3. **Instale as dependências:**
   ```
   pip install -r requirements.txt
   ```

4. **Rode o sistema:**
   ```
   python app.py
   ```

5. **Abra o navegador** em: http://127.0.0.1:5000

6. **Login padrão:**
   - Usuário: `admin`
   - Senha: `admin123`
   - Recomendo trocar a senha assim que entrar, no menu "Trocar senha".

O sistema cria automaticamente um arquivo `sistema.db` (banco de dados SQLite) na primeira execução — é onde tudo fica salvo. Basta fazer backup desse arquivo de vez em quando (copiar para um pendrive, Google Drive, etc.).

## O que o sistema faz

- **Dashboard**: faturamento do mês, despesas, lucro, fardos recebidos x entregues, médias diária/semanal/mensal, gráficos e resumo por espessura.
- **Entradas**: registre os fardos que chegam (data, espessura em cm, quantidade).
- **Saídas**: registre os fardos que você entrega prontos (o valor é calculado automaticamente).
- **Despesas**: lance custos do mês (energia, transporte, embalagens, etc.) para o lucro ficar correto.
- **Configurações**: aqui você define, para cada espessura (6cm, 8cm, 10cm, 15cm, 20cm, ou outras que adicionar), quantos sacos cabem em um fardo e quanto você recebe por saco de 12 unidades. O valor por fardo é calculado sozinho.

## Valores já configurados de fábrica

| Espessura | Sacos por fardo | Valor por saco | Valor por fardo |
|---|---|---|---|
| 10 cm | 125 | R$ 0,15 | R$ 18,75 |
| 15 cm | 72  | R$ 0,15 | R$ 10,80 |
| 20 cm | 54  | R$ 0,15 | R$ 8,10 |
| 6 cm  | -   | -       | *defina em Configurações* |
| 8 cm  | -   | -       | *defina em Configurações* |

Para o 6cm e 8cm, como você não me passou quantos sacos cabem em cada fardo, entre em **Configurações** e preencha — o valor do fardo é calculado na hora.

## Login padrão

Agora existem três tipos de login, cada um com um nível de acesso diferente:

| Usuário | Senha | O que consegue fazer |
|---|---|---|
| `gansotrue` | `130502` | **Admin** — acesso total: dashboard financeiro, entradas, saídas, despesas, relatórios em PDF e configurações |
| `texpharma` | `tex123` | **Somente visualização** — só vê quantos fardos entraram e saíram (sem nenhum valor em R$), não pode adicionar nem excluir nada |
| `funcionario` | `fun123` | **Lançamento de logística** — pode adicionar entradas e saídas (fardos), mas não vê nenhum valor em R$ e não pode excluir registros nem acessar despesas/configurações/relatórios |

Troque essas senhas em "Trocar senha" assim que possível (cada usuário troca a própria senha depois de logar).

## Fornecedores (Texpharma e Letícia)

Ao registrar uma entrada ou saída, agora você escolhe também o **fornecedor** (Texpharma ou Letícia), além da espessura. Cada fornecedor tem sua própria configuração de quantos sacos cabem no fardo e quanto vale cada saco — configure isso em **Configurações**, que agora tem uma tabela separada para cada fornecedor.

Os valores da Letícia vieram zerados porque você não tinha me passado os números ainda — entre em Configurações e preencha (sacos por fardo de cada espessura) para o sistema calcular o valor do fardo sozinho.

## Relatórios em PDF

Na aba **Relatórios** (só o admin vê), você escolhe:
- **Tipo**: Resumo Logístico (fardos: entrada x saída) ou Resumo Financeiro (faturamento, despesas, lucro)
- **Período**: Mensal (escolhendo mês/ano) ou Semanal (escolhendo qualquer dia daquela semana)

E clica em "Gerar PDF" — o arquivo é baixado na hora, pronto para imprimir ou enviar.

## Colocando no ar (GitHub + Render, com custo zero)

### Passo 1 — Subir o código no GitHub

1. Crie uma conta em https://github.com (se ainda não tiver).
2. Clique em **New repository**. Dê um nome (ex: `sistema-ataduras`) e marque como **Private** (assim só quem você convidar consegue ver o código).
3. Na página do repositório vazio, siga as instruções em "…or push an existing repository from the command line", ou simplesmente arraste todos os arquivos desta pasta pela interface web do GitHub (botão "Add file" → "Upload files").
   - **Importante:** não envie o arquivo `sistema.db` se ele já existir na sua pasta (o `.gitignore` já cuida disso se você usar o terminal com `git`).
4. Depois de subir, vá em **Settings → Collaborators** e adicione o e-mail/usuário do GitHub dos seus sócios, para que eles também tenham acesso ao código.

### Passo 2 — Hospedar no Render (gratuito)

1. Crie uma conta em https://render.com (dá pra entrar direto com sua conta do GitHub).
2. Clique em **New +** → **Web Service**.
3. Conecte sua conta do GitHub e selecione o repositório que você acabou de criar.
4. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
5. Em **Environment Variables**, adicione uma variável `SECRET_KEY` com um valor aleatório (qualquer texto longo e único, ex: `a8f9d2k3j4h5g6f7d8s9a0`). Isso protege os logins dos usuários.
6. Clique em **Create Web Service**. Em alguns minutos o Render vai te dar um link público, tipo `https://sistema-ataduras.onrender.com` — é esse link que você compartilha com seus sócios.

### 💾 Banco de dados: use um PostgreSQL externo (recomendado, resolve o problema de perder dados)

O sistema já vem pronto para funcionar tanto com o arquivo local (`sistema.db`, usado quando você roda no seu PC) quanto com um **banco de dados externo PostgreSQL** — que é o que você deve usar em produção, porque ele existe fora do Render e não é apagado quando o serviço reinicia.

**Passo a passo (usando o Neon, gratuito e simples):**

1. Crie uma conta em https://neon.tech (dá pra entrar com GitHub).
2. Crie um novo projeto (**New Project**). Dê um nome, ex: `ataduras`.
3. Depois de criado, o Neon te mostra uma **Connection String**, algo como:
   ```
   postgresql://usuario:senha@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
   Copie essa string inteira.
4. No Render, vá até o seu Web Service → **Environment** → adicione uma variável:
   - **Key:** `DATABASE_URL`
   - **Value:** cole a string que você copiou do Neon
5. Clique em **Save Changes** — o Render reinicia o serviço automaticamente e passa a usar esse banco. A partir de agora, mesmo que o serviço reinicie ou você suba código novo, **seus dados continuam salvos no Neon**, intactos.

Outras opções equivalentes ao Neon, caso prefira: **Supabase** (https://supabase.com) ou o próprio **Render Postgres** (Render → New + → PostgreSQL — grátis, mas expira depois de alguns meses no plano free).

**Testando localmente com o banco externo (opcional):** se quiser rodar no seu PC já conectado ao banco do Neon (por exemplo, pra você e seus sócios sempre verem os mesmos dados mesmo testando localmente), crie a variável de ambiente antes de rodar:
```
# Windows (PowerShell)
$env:DATABASE_URL="postgresql://usuario:senha@ep-xxxxx.neon.tech/neondb?sslmode=require"
python app.py

# Mac/Linux
export DATABASE_URL="postgresql://usuario:senha@ep-xxxxx.neon.tech/neondb?sslmode=require"
python app.py
```
Sem essa variável definida, o sistema usa o arquivo local `sistema.db` automaticamente — nada muda no seu dia a dia de testes.

## Segurança

- Troque a chave secreta (`SECRET_KEY`) antes de usar com dados reais — no Render, isso é feito nas "Environment Variables" (Passo 2.5 acima); localmente, você pode criar um arquivo `.env` ou exportar a variável no terminal.
- Troque a senha padrão assim que possível.
- Mantenha o repositório do GitHub como **Private** e só adicione como colaboradores as pessoas de confiança (seus sócios).

## Sacos produzidos

O dashboard e os relatórios em PDF agora também mostram quantos **sacos** (pacotes de 12 unidades) foram produzidos, calculado automaticamente como `quantidade de fardos entregues × sacos por fardo` (configurado em Configurações, por espessura e fornecedor). Esse número é visível para todos os logins, já que não envolve valores em R$.

## Fotos em entradas e saídas

Ao lançar uma entrada ou saída, agora existe um campo opcional de **Foto** — pode tirar uma foto na hora (no celular, abre a câmera direto) ou escolher uma imagem já salva. As fotos aparecem como uma miniatura na tabela de registros (clique para ver em tamanho grande) e podem ser trocadas ou removidas na tela de edição (admin).

As fotos ficam salvas dentro do próprio banco de dados (Postgres/Neon), então elas são preservadas normalmente nos backups e não dependem do disco do Render.

## Uso pelo celular

O sistema agora tem um layout responsivo: no celular, o menu lateral vira um menu "hambúrguer" (ícone no topo) que abre por cima da tela, os formulários ficam empilhados em coluna única, e as tabelas grandes deslizam horizontalmente com o dedo quando necessário.

## Módulo de Produção (funcionários que enfardam)

Dois novos logins para os funcionários que fazem o enfardamento (Clare e Gabriel):

| Usuário | Senha inicial | Acesso |
|---|---|---|
| `clare` | `1234` | Lança a própria produção + vê o próprio dashboard (ganhos) |
| `gabriel` | `1234` | Lança a própria produção + vê o próprio dashboard (ganhos) |

**Na primeira vez que logam, são obrigados a trocar a senha** antes de conseguir usar qualquer outra parte do sistema.

Cada um só vê e lança a **própria** produção — nunca a do outro. Ao lançar, preenchem data, marca (Texpharma/Letícia), espessura, quantidade de fardos, observação (opcional) e **foto obrigatória** do que foi produzido.

O dashboard deles é simplificado: fardos produzidos, quanto ganharam no mês (baseado numa taxa por fardo que você configura) e um gráfico simples — sem nenhum acesso a valores financeiros da empresa, despesas, entradas/saídas ou relatórios.

**Taxa de pagamento por fardo:** configurável em Configurações → "Taxa paga aos funcionários de produção". Valores iniciais: 10cm = R$3,00 · 15cm = R$2,00 · 20cm = R$1,50 (6cm e 8cm vêm zerados, preencha se for usar).

**Você (admin) vê tudo:** a página "Produção (funcionários)" no menu mostra todos os lançamentos de todos os funcionários, com fotos, valores e opção de editar/excluir. E o melhor: **o custo de mão de obra deles entra automaticamente no seu Lucro do mês** (aparece dentro do card "Despesas do mês" e também nos relatórios em PDF financeiro) — você não precisa lançar isso manualmente como despesa.
