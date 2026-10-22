# Acervo IFC · Campus Fraiburgo

Aplicação de controle da entrega e devolução dos livros didáticos do curso Técnico em Informática Integrado ao Ensino Médio. O termo e as regras foram adaptados do documento `documentos/Termo de compromisso.pdf`.

## Organização do projeto

A aplicação segue o padrão **MVC** (Model–View–Controller), com uma camada de serviço para manter as regras de negócio independentes das rotas e do banco:

```text
acervo/
├── controllers.py   # Rotas HTTP, sessão e respostas JSON
├── models.py        # Catálogo, validações e regras do domínio
├── repository.py    # Persistência e consultas SQLite
├── services.py      # Casos de uso e validações do negócio
├── templates/
│   └── index.html   # View renderizada pelo Flask
└── static/
    ├── app.js       # Interações da interface
    └── styles.css   # Estilos
server.py            # Inicialização e comando administrativo
test_app.py          # Testes da aplicação
```

As dependências seguem o sentido **Controller → Service → Repository**. A view conversa com os controllers pela API HTTP; assim, interface, regras e persistência podem evoluir separadamente. `create_app()` configura cada instância, o que também permite testar a aplicação com um banco temporário sem tocar nos dados locais.

## Executar localmente

Requer Python 3.10 ou superior.

```powershell
python -m pip install -r requirements.txt
python server.py create-user
python server.py
```

No primeiro acesso, crie uma conta de servidor pelo comando `create-user`, usando um e-mail `@ifc.edu.br` e uma senha com pelo menos 12 caracteres. A aplicação abre em `http://127.0.0.1:5000`. O banco SQLite `livros.db` é criado localmente e persiste os cadastros e assinaturas.

Defina `SECRET_KEY` com um segredo aleatório persistente antes de hospedar a aplicação e configure `COOKIE_SECURE=true` quando servida por HTTPS. Faça cópias de segurança do banco de dados e proteja seu acesso.

## Docker Compose

São fornecidas configurações independentes para desenvolvimento e produção. Requer Docker Engine e o plugin Docker Compose.

### Desenvolvimento

O modo dev ativa a recarga automática do Flask, monta o código-fonte no container e espelha o arquivo `livros.db` do projeto diretamente em `/data/livros.db` dentro do container. O cookie HTTPS é desativado somente para uso local.

```powershell
if (-not (Test-Path .\livros.db)) { New-Item -ItemType File -Path .\livros.db }
docker compose -f docker-compose.dev.yml up --build
```

Acesse `http://localhost:5000`. Para criar a conta de servidor em outro terminal:

```powershell
docker compose -f docker-compose.dev.yml run --rm web python server.py create-user
```

Encerre com `Ctrl+C`; use `docker compose -f docker-compose.dev.yml down` para parar o serviço. Os dados ficam no arquivo `livros.db` do host e continuam disponíveis depois de remover ou recriar o container.

### Produção

1. Copie `.env.example` para `.env` e defina `SECRET_KEY` com um valor aleatório exclusivo:

   ```powershell
   Copy-Item .env.example .env
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Grave o valor gerado em `SECRET_KEY` no `.env`. O Compose exige uma chave não vazia. Mantenha `COOKIE_SECURE=true` quando a aplicação estiver publicada por HTTPS.
3. Confirme que o arquivo `livros.db` existe no projeto. Se estiver configurando uma instalação nova sem banco existente, crie o arquivo vazio antes de iniciar:

   ```powershell
   if (-not (Test-Path .\livros.db)) { New-Item -ItemType File -Path .\livros.db }
   ```

   Se já usa `livros.db`, mantenha-o no lugar: o Compose vai montar o mesmo arquivo e a aplicação preservará seus registros.
4. Inicie a aplicação:

   ```powershell
   docker compose up --build -d
   ```

5. Crie a conta inicial do servidor:

   ```powershell
   docker compose run --rm web python server.py create-user
   ```

O servidor Gunicorn escuta na porta 8000 do container; `HOST_PORT` define a porta do host (padrão `8000`). A porta do host é vinculada somente a `127.0.0.1`, para acesso por um proxy reverso HTTPS instalado no mesmo host, sem expor o servidor diretamente à rede. O arquivo `livros.db` na raiz do projeto é montado como bind mount em `/data/livros.db` no container. As alterações aparecem diretamente no arquivo do host, persistem mesmo após remover containers e não dependem de volumes Docker. O Compose exige que o arquivo exista antes da inicialização para evitar criar por engano uma pasta chamada `livros.db`.

Os modos dev e production usam o mesmo arquivo `livros.db`; não execute os dois ao mesmo tempo nem use dados reais em desenvolvimento.

Faça backups regulares. Para produzir uma cópia consistente, pare o serviço, copie o arquivo no host e inicie-o novamente:

```powershell
docker compose stop web
Copy-Item .\livros.db .\livros-backup.db
docker compose up -d
```

Proteja os arquivos de backup e não os inclua no controle de versão. `.gitignore` exclui o banco, seus arquivos auxiliares SQLite e o `.env`.

Para atualizar a imagem após mudanças, execute `docker compose up --build -d`. Para parar sem remover dados: `docker compose down`. O arquivo `livros.db` permanece no host independentemente do ciclo de vida dos containers.

## Fluxo

- Cadastre cada estudante com nome, matrícula única e ano (1º, 2º ou 3º).
- Na tela **Estudantes**, use **Baixar modelo CSV** para obter uma planilha vazia com os cabeçalhos `matricula`, `nome` e `turma`; preencha-a e importe pelo botão **Importar CSV**. A turma pode ser `1`, `1º`, `1°` ou `1º ano` (equivalente para 2º e 3º). Também são aceitos arquivos separados por vírgula ou tabulação e o cabeçalho `matrícula`. Linhas com matrícula já cadastrada, inclusive repetidas no mesmo arquivo, são ignoradas; linhas inválidas são informadas ao final.
- Abra o termo para registrar a assinatura manuscrita do estudante em cada título entregue.
- Na devolução, o servidor registra a assinatura título por título. A devolução só fica disponível depois da entrega.
- Use **Exportar PDF** e escolha **Salvar como PDF** no diálogo de impressão do navegador. O termo inclui o registro de cada assinatura já feita e os espaços ainda pendentes.

Exemplo de CSV (UTF-8, cabeçalhos na primeira linha):

```csv
matricula;nome;turma
202612345;Ana da Silva;1º
202612346;João Souza;2º ano
```

Cada ano letivo tem seu próprio termo. Ao iniciar um novo ano, estudantes ativos são promovidos automaticamente (1º→2º e 2º→3º); quem concluiu o 3º ano fica arquivado, sem novo termo ativo. O ciclo e a turma histórica ficam preservados, e é possível selecionar anos anteriores no detalhe do estudante e exportar o termo daquele ano em PDF.

Português e Matemática são específicos da turma e do ano letivo. Os outros 13 títulos são volumes únicos: um empréstimo ainda não devolvido acompanha o estudante nos ciclos seguintes, sem gerar uma nova assinatura de entrega. Títulos já devolvidos não são reemitidos automaticamente. Ao corrigir a turma no ciclo atual, os novos volumes anuais são acrescentados sem apagar assinaturas anteriores. Cada assinatura é registrada com data e hora; a devolução também guarda o e-mail do servidor autenticado.

O ano letivo é controlado por `SCHOOL_YEAR` (por padrão, o ano corrente). É possível defini-lo explicitamente no ambiente para ajustar o calendário escolar; a mudança para um ano posterior cria os ciclos e promoções faltantes na próxima inicialização do app. Não reduza o ano configurado depois que os ciclos futuros tiverem sido criados.

## Autenticação

O acesso atual usa conta e senha, com senha armazenada em hash e sessão protegida. Contas são provisionadas pelo administrador via `create-user`; não há cadastro público nem verificação automática de domínio. O botão Google permanece desativado: OAuth não está conectado até que o campus configure um provedor OIDC e suas credenciais e URLs de callback. Não publique este servidor diretamente na internet sem configurar esses controles e uma política de backup.

As assinaturas manuscritas são armazenadas como imagens junto às datas e ao registro do servidor. Validade jurídica e requisitos de assinatura eletrônica devem ser avaliados pelo IFC antes do uso oficial.

## Verificações

```powershell
python -m unittest
```
