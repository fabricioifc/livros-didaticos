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
│   └── index.html   # Interface do servidor
└── static/
    ├── js/
    │   ├── main.js            # Inicialização e eventos globais
    │   ├── state.js, dom.js   # Estado da interface e elementos
    │   ├── api.js, utils.js   # Cliente HTTP, avisos e utilitários
    │   ├── auth.js            # Login e sessão
    │   ├── navigation.js      # Menu, abas e telas
    │   ├── students.js        # Listagem, filtros, cadastro e importação
    │   ├── student-detail.js  # Termo do estudante (cadastro ou entrega) e seleção de livros
    │   ├── loans.js           # Tela Entrega e devolução: busca por matrícula ou nome
    │   ├── history.js         # Histórico e correções
    │   ├── signature.js       # Assinatura em canvas
    │   ├── print.js           # Impressão de termos e backups
    │   ├── courses.js         # Cursos (opções e filtros)
    │   └── admin.js           # Cursos, usuários e ano letivo
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

Defina `SECRET_KEY` com um segredo aleatório persistente antes de hospedar a aplicação e configure `COOKIE_SECURE=true` quando servida por HTTPS.

### Sessão e login

- Fora do `server.py`, a aplicação não inicia sem `SECRET_KEY`. Localmente, o `server.py` gera uma chave temporária, e as sessões caem a cada reinício.
- A sessão expira após 12 horas do login (`SESSION_MAX_AGE`) ou 30 minutos sem uso (`SESSION_IDLE_TIMEOUT`). Os dois valores são em segundos.
- Sair da conta encerra as sessões do usuário em todos os dispositivos. Desativar uma conta também invalida as sessões existentes, mesmo que ela seja reativada depois.
- Após 5 tentativas de login com erro para o mesmo e-mail, novas tentativas ficam bloqueadas por 15 minutos. Faça cópias de segurança do banco de dados e proteja seu acesso.

## Docker Compose

São fornecidas configurações independentes para desenvolvimento e produção. Requer Docker Engine e o plugin Docker Compose.

### Desenvolvimento

O modo dev ativa a recarga automática do Flask, monta o código-fonte no container e usa o banco isolado `data-dev/livros.db` do host. A produção continua usando `data/livros.db`, evitando que testes ou resets de desenvolvimento alterem dados reais. O arquivo e a pasta são criados automaticamente na primeira inicialização; um serviço inicializador prepara permissões para o usuário não-root da aplicação. O cookie HTTPS é desativado somente para uso local.

```powershell
docker compose -f docker-compose.dev.yml up --build
```

Acesse `http://localhost:5000`. Para criar a conta de servidor em outro terminal:

```powershell
docker compose -f docker-compose.dev.yml run --rm web python server.py create-user
```

Para limpar somente os estudantes do banco dev, voltar ao ano corrente e carregar três estudantes fictícios de demonstração, execute:

```powershell
docker compose -f docker-compose.dev.yml run --rm web python server.py reset-dev-data
```

O comando preserva as contas de servidores, apaga os registros estudantis do banco de desenvolvimento e recria os ciclos para o ano atual. Ele é bloqueado fora do serviço configurado com `APP_ENV=development`. Encerre com `Ctrl+C`; use `docker compose -f docker-compose.dev.yml down` para parar o serviço. Os dados dev ficam em `data-dev\livros.db` e continuam disponíveis depois de remover ou recriar o container.

### Produção

1. Copie `.env.example` para `.env` e defina `SECRET_KEY` com um valor aleatório exclusivo:

   ```powershell
   Copy-Item .env.example .env
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Grave o valor gerado em `SECRET_KEY` no `.env`. O Compose exige uma chave não vazia. Mantenha `COOKIE_SECURE=true` quando a aplicação estiver publicada por HTTPS.
3. O banco é criado automaticamente em `data\livros.db` no primeiro início; não é necessário criar o arquivo manualmente. Se você já possui um banco antigo em `livros.db` na raiz do projeto, pare os containers e migre-o antes de iniciar a nova configuração:

   ```powershell
   New-Item -ItemType Directory -Force -Path .\data
   Move-Item .\livros.db .\data\livros.db
   ```

   Se preferir manter uma cópia original, use `Copy-Item` em vez de `Move-Item`; confirme que o arquivo em `data\livros.db` contém os dados esperados antes de subir os containers.
4. Inicie a aplicação:

   ```powershell
   docker compose up --build -d
   ```

5. Crie a conta inicial do servidor:

   ```powershell
   docker compose run --rm web python server.py create-user
   ```

O Gunicorn escuta na porta 8000 somente na rede interna do Compose; a porta não é publicada no host. O Nginx encaminha as requisições para o serviço `web` e publica a porta local `127.0.0.1:8000` (configurável por `HOST_PORT`). O banco em `data\livros.db` é montado em `/data/livros.db` no container e espelhado no host. O Compose prepara automaticamente a pasta, o arquivo inicial e as permissões do banco.

### Cloudflare Tunnel com Nginx

No painel do Cloudflare Zero Trust, configure a rota pública do túnel para o hostname desejado com serviço de origem `http://localhost:8000` (ou a porta definida em `HOST_PORT`). O TLS público termina no Cloudflare; o túnel conecta ao Nginx local por HTTP. Não configure o túnel para apontar diretamente à porta interna do Gunicorn. Se seu túnel já usava `localhost:8000`, essa origem continua igual: a porta agora pertence ao Nginx, não ao Gunicorn.

Essa instrução presume que `cloudflared` está instalado no host que executa o Docker Compose. Se o `cloudflared` estiver em outro container, `localhost` apontará para esse container: conecte-o à mesma rede Docker e use `http://nginx:80` como origem, ou direcione-o ao endereço do host e à porta `HOST_PORT`. Mantenha a porta do Nginx vinculada a `127.0.0.1` quando o túnel estiver no host, para que não fique acessível diretamente pela rede.

O arquivo `nginx/default.conf` configura o proxy e encaminha o host original, IPs e protocolo recebidos. O limite do corpo de requisição de 2 MB permite as assinaturas, respeitando o limite da aplicação. O Compose espera o Gunicorn ficar saudável antes de iniciar o Nginx.

Os modos dev e production usam o mesmo arquivo `data\livros.db`; não execute os dois ao mesmo tempo nem use dados reais em desenvolvimento.

Antes de cada avanço do ano letivo, a aplicação cria e valida uma cópia completa do banco SQLite antes de alterar os ciclos. O backup fica no diretório `data\backups` em produção (`data-dev\backups` no ambiente de desenvolvimento), dentro do volume persistente `/data`, e também é disponibilizado para download ao administrador após a migração. Em execução local, o diretório padrão é `backups`, ao lado do banco. Esses arquivos contêm dados pessoais, assinaturas e hashes de senha: restrinja o acesso, não os publique e mantenha cópias periódicas em outro local protegido.

Na aba **Administração → Backup**, o administrador pode criar um backup completo a qualquer momento (o arquivo é guardado no mesmo diretório e baixado em seguida), baixar os backups existentes no servidor e restaurar um backup enviando o arquivo SQLite (até 64 MB). Antes de restaurar, a aplicação valida o arquivo e cria um backup de segurança do banco atual; se a troca falhar, o banco anterior é recuperado. Após a restauração, todas as sessões são encerradas e é preciso entrar com uma conta existente no backup. O `nginx/default.conf` aceita uploads maiores apenas nessa rota.

O servidor mantém no máximo os 5 backups mais recentes, contando os manuais, os do avanço do ano letivo e os de segurança da restauração. Ao criar um novo, os mais antigos são apagados automaticamente; guarde fora do servidor as cópias que precisar manter por mais tempo.

Para produzir uma cópia manual adicional do banco, pare o serviço, copie o arquivo no host e inicie-o novamente:

```powershell
docker compose stop nginx web
Copy-Item .\data\livros.db .\livros-backup.db
docker compose up -d
```

Proteja os arquivos de backup e não os inclua no controle de versão. `.gitignore` exclui o banco, seus arquivos auxiliares SQLite e o `.env`.

Para atualizar as imagens após mudanças, execute `docker compose up --build -d`. Para parar sem remover dados: `docker compose down`. O arquivo `data\livros.db` permanece no host independentemente do ciclo de vida dos containers.

## Fluxo

- Cadastre cada estudante com nome, matrícula única de exatamente 10 dígitos (por exemplo, `2026304710`), curso e ano (1º, 2º ou 3º). A matrícula pode ser corrigida em **Editar cadastro**, desde que não pertença a outro estudante; entregas, devoluções e histórico acompanham a nova matrícula. Os termos PDF listam os livros em ordem alfabética pelo título.
- Os cursos **INFO** (Técnico em Informática Integrado ao Ensino Médio) e **ADM** (Técnico em Administração Integrado ao Ensino Médio) são cadastrados inicialmente. Administradores podem adicionar cursos e siglas de 3 a 5 caracteres na seção **Administração → Cursos**, em abas separadas de **Ano letivo** e **Usuários**, e ativar ou desativar cursos. Cursos já vinculados a estudantes não são apagados; ao desativá-los, os vínculos e termos existentes permanecem.
- Na migração, os estudantes que já estavam cadastrados antes da inclusão dos cursos recebem o vínculo inicial com **INFO — Técnico em Informática Integrado ao Ensino Médio**. O vínculo pode ser ajustado no cadastro de cada estudante. Se já existirem outros cursos sem sigla, o sistema atribui uma sigla provisória, que pode ser usada até 5 caracteres.
- Em **Administração → Estudantes**, use **Baixar modelo CSV** para obter uma planilha com os cabeçalhos `matricula`, `nome`, `turma` e `curso` e duas linhas de exemplo, uma de cada curso padrão (substitua-as pelos estudantes reais antes de importar); preencha o curso com a sigla ou o nome cadastrado e importe pelo botão **Importar CSV**. A turma pode ser `1`, `1º`, `1°` ou `1º ano` (equivalente para 2º e 3º). Também são aceitos arquivos separados por vírgula ou tabulação e o cabeçalho `matrícula`. Linhas com matrícula já cadastrada, inclusive repetidas no mesmo arquivo, são ignoradas; linhas inválidas são informadas ao final.
- O cadastro de estudantes fica em **Administração → Estudantes** e é restrito a administradores, inclusive no servidor: cadastrar, importar, editar, desvincular, reativar, excluir e exportar os termos do ano exigem perfil de administrador. Abrir um estudante ali mostra o termo apenas para consulta, com edição, desvinculação e exportação. Qualquer servidor pode consultar estudantes e registrar retiradas e devoluções. Entregas e devoluções ficam na tela **Entrega e devolução**, que é a página inicial e aparece em destaque no menu: pesquise pela matrícula ou pelo nome (sem precisar de acentos) e abra o termo; Enter abre o primeiro resultado. Estudantes com ciclo concluído ou desvinculados também aparecem, para registrar devoluções. No cadastro, **Entrega e devolução** leva o termo aberto para esse fluxo.
- No termo aberto em **Entrega e devolução**, selecione um ou mais livros pendentes e escolha **Assinar entrega dos selecionados**. Use **Selecionar todos** para marcar de uma vez os livros que ainda podem ser entregues no ciclo atual. A tela de assinatura abre direto, com a lista dos títulos, e a mesma assinatura é registrada em cada livro selecionado. O servidor só aceita a assinatura como imagem PNG íntegra, no formato gerado pelo campo de assinatura, e com algum traço; um campo em branco é recusado. Entregas são registradas apenas por essa seleção de livros do termo; a rota individual por livro aceita somente devoluções.
- Na tela da assinatura ou ao lado de cada livro, abra **Ver histórico e corrigir registro** / **Histórico** para consultar assinaturas, devoluções e correções anteriores. Se uma entrega ou devolução foi registrada por engano ou a assinatura precisa ser refeita, cancele o registro ativo e informe o motivo. O histórico original não é apagado; cada cancelamento também registra data, servidor responsável e justificativa. Para cancelar uma entrega que já tem devolução registrada, cancele primeiro a devolução.
- O portal do estudante, a autenticação estudantil e a verificação por QR Code estão desativados. Dados de credenciais antigos, se presentes em um banco existente, são preservados sem uso pela aplicação.
- Na devolução, o servidor registra a assinatura título por título. A devolução só fica disponível depois da entrega.
- Estudantes que concluíram o 3º ano ficam arquivados e aparecem em **Administração → Estudantes** pelo filtro **Arquivados**, em vez de aparecerem como estudantes ativos do 3º ano.
- Use **Exportar PDF** para salvar o termo do ano selecionado. Para exportar juntos todos os termos de um estudante, inclusive os três ciclos de quem concluiu o Ensino Médio, abra o estudante e use **Exportar todos os termos**.
- Para administradores, o botão **Exportar termos do ano**, no topo da tela, permite selecionar o ano e reúne em um único PDF todos os termos daquele ciclo, incluindo estudantes arquivados que estudaram naquele ano. No diálogo de impressão, selecione **Salvar como PDF**; cada termo começa em uma nova página.

Exemplo de CSV (UTF-8, cabeçalhos na primeira linha):

```csv
matricula;nome;turma;curso
2026304710;Ana da Silva;1º;Técnico em Informática Integrado ao Ensino Médio
2026304711;João Souza;2º ano;Técnico em Administração Integrado ao Ensino Médio
```

Cada ano letivo tem seu próprio termo. Ao iniciar um novo ano, estudantes ativos são promovidos automaticamente (1º→2º e 2º→3º); quem concluiu o 3º ano fica arquivado, sem novo termo ativo. O ciclo, a turma histórica e a relação de títulos de cada termo ficam preservados, e é possível selecionar anos anteriores no detalhe do estudante e exportar o termo daquele ano em PDF.

Os títulos vêm do catálogo em **Administração → Livros**, onde o administrador cadastra, edita, desativa e exclui livros. Cada livro tem uma aplicação:

- **Ano específico (1º, 2º ou 3º):** entregue a cada ciclo letivo aos estudantes daquele ano (como Português e Matemática).
- **Volume único:** vale para os três anos. Um empréstimo ainda não devolvido acompanha o estudante nos ciclos seguintes, sem nova assinatura de entrega; títulos já devolvidos não são reemitidos.

O catálogo começa com os 19 títulos usados até então (Português e Matemática para cada ano e 13 volumes únicos). Cadastrar, reativar ou desativar um livro altera os termos do ano letivo atual, sem mexer em livros já entregues nem em ciclos anteriores. Um livro com entregas registradas não pode ser excluído nem mudar de aplicação; desative-o. Os termos já assinados mantêm o título da época da entrega. Ao corrigir a turma no ciclo atual, os livros do novo ano são acrescentados sem apagar assinaturas anteriores. Cada assinatura é registrada com data e hora; a devolução também guarda o e-mail do servidor autenticado.

O ano letivo inicial vem de `SCHOOL_YEAR` (por padrão, o ano corrente) e fica persistido no banco. Um administrador também pode alterá-lo na seção **Usuários → Ano letivo**: antes de avançar, a aplicação cria e valida um backup completo do banco; se essa etapa falhar, o ano não é alterado. Após o avanço, os ciclos e promoções faltantes são criados imediatamente e o backup fica disponível para download. Depois, novos ingressantes podem ser cadastrados/importados como 1º ano. A alteração vale para todos os servidores e persiste após reinícios, prevalecendo sobre uma variável de ambiente anterior. Não é permitido voltar para um ano menor, pois isso poderia reativar termos arquivados ou desfazer promoções; confira o ano antes de confirmar.

## Autenticação e usuários

O acesso usa conta e senha, com senha armazenada em hash e sessão protegida. A conta `fabricio.bizotto@ifc.edu.br` é promovida a administradora na inicialização do banco. Para criá-la no primeiro uso, execute `create-user` e informe esse e-mail; a senha não é criada automaticamente:

```powershell
docker compose run --rm web python server.py create-user
```

Administradores veem a seção **Administração**, organizada nas abas **Cursos**, **Ano letivo** e **Usuários**. Podem cadastrar contas `@ifc.edu.br`, promover servidores a administradores e ativar/desativar contas. O menu lateral pode ser recolhido pelo botão no topo da página. Contas desativadas não podem entrar e sessões já abertas perdem o acesso na próxima requisição. O sistema impede que o administrador remova o próprio acesso pela interface ou que a última conta administradora ativa seja desativada/rebaixada. Não há cadastro público nem recuperação de senha implementados.

O login com e-mail e senha continua disponível. O **login com Google** é opcional e só aparece quando `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` e `GOOGLE_REDIRECT_URI` estão configurados (veja `.env.example`). Para ativá-lo:

1. No Google Cloud Console, crie um cliente OAuth do tipo **Aplicativo da Web** e cadastre como URI de redirecionamento autorizada o endereço público seguido de `/api/auth/google/callback` (por exemplo, `https://acervo.exemplo.ifc.edu.br/api/auth/google/callback`). A tela de consentimento pode ser do tipo **Interno**, restrita à organização.
2. Preencha as três variáveis no `.env`; `GOOGLE_REDIRECT_URI` deve ser idêntica à cadastrada.
3. Reinicie a aplicação.

O Google não cria contas: entra apenas quem já tem conta **ativa** no Acervo com o mesmo e-mail, que precisa ser `@ifc.edu.br` e verificado pelo Google. Perfil (servidor ou administrador), desativação e encerramento de sessões seguem as mesmas regras do login com senha. O fluxo usa `state`, `nonce` e PKCE, e o servidor confere emissor, público, validade e domínio do ID token. Não publique este servidor diretamente na internet sem configurar esses controles e uma política de backup.

As assinaturas manuscritas são armazenadas como imagens junto às datas e ao registro do servidor. O QR autentica a sessão do estudante, mas não substitui a avaliação institucional sobre validade jurídica e requisitos de assinatura eletrônica. Validade jurídica e uso de credenciais por estudantes menores de idade devem ser avaliados pelo IFC antes do uso oficial.

## Privacidade

O aviso de privacidade está disponível publicamente em `/privacidade` e pelo link na tela de acesso e no rodapé da aplicação. Ele descreve os dados arquivados para controle interno, quem pode acessá-los, o contexto de estudantes adolescentes, serviços técnicos envolvidos e direitos dos titulares. Antes de usar dados reais em produção, o IFC deve validar o texto, definir e registrar a base legal e o prazo de retenção e inserir o canal institucional atualizado do encarregado de dados pessoais.

## Verificações

```powershell
python -m unittest
```
