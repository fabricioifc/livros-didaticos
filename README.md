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
│   ├── index.html   # View do servidor
│   └── student.html # Portal individual do estudante
└── static/
    ├── app.js       # Interações da interface
    ├── student.js  # Login e QR temporário do estudante
    ├── vendor/qr-scanner/ # Leitor QR local (qr-scanner 1.4.2, MIT)
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

O modo dev ativa a recarga automática do Flask, monta o código-fonte no container e espelha `data/livros.db` do host em `/data/livros.db` dentro do container. O arquivo e a pasta são criados automaticamente na primeira inicialização; um serviço inicializador prepara permissões para o usuário não-root da aplicação. O cookie HTTPS é desativado somente para uso local.

```powershell
docker compose -f docker-compose.dev.yml up --build
```

Acesse `http://localhost:5000`. Para criar a conta de servidor em outro terminal:

```powershell
docker compose -f docker-compose.dev.yml run --rm web python server.py create-user
```

Encerre com `Ctrl+C`; use `docker compose -f docker-compose.dev.yml down` para parar o serviço. Os dados ficam no arquivo `data\livros.db` do host e continuam disponíveis depois de remover ou recriar o container.

### Produção

1. Copie `.env.example` para `.env` e defina `SECRET_KEY` com um valor aleatório exclusivo:

   ```powershell
   Copy-Item .env.example .env
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Grave o valor gerado em `SECRET_KEY` no `.env`. O Compose exige uma chave não vazia. Mantenha `COOKIE_SECURE=true` quando a aplicação estiver publicada por HTTPS.
3. Defina `PUBLIC_BASE_URL` no `.env` com o endereço público completo da aplicação, sem barra final (por exemplo, `https://acervo.exemplo.edu.br`). Esse endereço é usado no QR Code do portal do estudante; não use `localhost` na configuração de produção.
4. O banco é criado automaticamente em `data\livros.db` no primeiro início; não é necessário criar o arquivo manualmente. Se você já possui um banco antigo em `livros.db` na raiz do projeto, pare os containers e migre-o antes de iniciar a nova configuração:

   ```powershell
   New-Item -ItemType Directory -Force -Path .\data
   Move-Item .\livros.db .\data\livros.db
   ```

   Se preferir manter uma cópia original, use `Copy-Item` em vez de `Move-Item`; confirme que o arquivo em `data\livros.db` contém os dados esperados antes de subir os containers.
5. Inicie a aplicação:

   ```powershell
   docker compose up --build -d
   ```

6. Crie a conta inicial do servidor:

   ```powershell
   docker compose run --rm web python server.py create-user
   ```

O Gunicorn escuta na porta 8000 somente na rede interna do Compose; a porta não é publicada no host. O Nginx encaminha as requisições para o serviço `web` e publica a porta local `127.0.0.1:8000` (configurável por `HOST_PORT`). O banco em `data\livros.db` é montado em `/data/livros.db` no container e espelhado no host. O Compose prepara automaticamente a pasta, o arquivo inicial e as permissões do banco.

### Cloudflare Tunnel com Nginx

No painel do Cloudflare Zero Trust, configure a rota pública do túnel para o hostname desejado com serviço de origem `http://localhost:8000` (ou a porta definida em `HOST_PORT`). O TLS público termina no Cloudflare; o túnel conecta ao Nginx local por HTTP. Não configure o túnel para apontar diretamente à porta interna do Gunicorn. Se seu túnel já usava `localhost:8000`, essa origem continua igual: a porta agora pertence ao Nginx, não ao Gunicorn.

Essa instrução presume que `cloudflared` está instalado no host que executa o Docker Compose. Se o `cloudflared` estiver em outro container, `localhost` apontará para esse container: conecte-o à mesma rede Docker e use `http://nginx:80` como origem, ou direcione-o ao endereço do host e à porta `HOST_PORT`. Mantenha a porta do Nginx vinculada a `127.0.0.1` quando o túnel estiver no host, para que não fique acessível diretamente pela rede.

O arquivo `nginx/default.conf` configura o proxy e encaminha o host original, IPs e protocolo recebidos. O limite do corpo de requisição de 2 MB permite as assinaturas, respeitando o limite da aplicação. O Compose espera o Gunicorn ficar saudável antes de iniciar o Nginx.

Os modos dev e production usam o mesmo arquivo `data\livros.db`; não execute os dois ao mesmo tempo nem use dados reais em desenvolvimento.

Faça backups regulares. Para produzir uma cópia consistente, pare o serviço, copie o arquivo no host e inicie-o novamente:

```powershell
docker compose stop nginx web
Copy-Item .\data\livros.db .\livros-backup.db
docker compose up -d
```

Proteja os arquivos de backup e não os inclua no controle de versão. `.gitignore` exclui o banco, seus arquivos auxiliares SQLite e o `.env`.

Para atualizar as imagens após mudanças, execute `docker compose up --build -d`. Para parar sem remover dados: `docker compose down`. O arquivo `data\livros.db` permanece no host independentemente do ciclo de vida dos containers.

## Fluxo

- Cadastre cada estudante com nome, matrícula única e ano (1º, 2º ou 3º).
- Na tela **Estudantes**, use **Baixar modelo CSV** para obter uma planilha vazia com os cabeçalhos `matricula`, `nome` e `turma`; preencha-a e importe pelo botão **Importar CSV**. A turma pode ser `1`, `1º`, `1°` ou `1º ano` (equivalente para 2º e 3º). Também são aceitos arquivos separados por vírgula ou tabulação e o cabeçalho `matrícula`. Linhas com matrícula já cadastrada, inclusive repetidas no mesmo arquivo, são ignoradas; linhas inválidas são informadas ao final.
- Abra o termo para registrar a assinatura manuscrita do estudante em cada título entregue.
- Para habilitar a confirmação por QR, um administrador abre o estudante e usa **Gerar acesso do aluno**. Após conferir presencialmente a identidade, entregue ao estudante o código temporário de 4 dígitos por um canal seguro. O modal também mostra um QR Code que abre o portal do estudante no endereço público configurado. O estudante entra com matrícula e código temporário e cria uma senha pessoal (mínimo de 12 caracteres). Após cinco tentativas incorretas, o acesso fica bloqueado por 15 minutos.
- No momento da retirada, o estudante entra em `/aluno` e gera um QR Code com um código numérico de seis dígitos, válido por 90 segundos. No detalhe do estudante, o servidor seleciona **Assinar entrega**, escaneia o QR pela câmera ou digita os seis dígitos exibidos pelo estudante se a leitura falhar; após a validação, o estudante assina na tela. A câmera exige HTTPS (o Cloudflare Tunnel fornece esse contexto) e permissão do navegador. O mesmo código pode ser usado para registrar vários livros enquanto estiver válido; ele está associado à matrícula e ao ano letivo. Gerar outro código invalida o anterior. Após cinco tentativas incorretas de validação, o acesso do servidor fica bloqueado por 15 minutos. Devoluções continuam sendo registradas pelo servidor sem QR.
- O administrador pode redefinir o acesso do estudante; o código temporário é exibido uma única vez. Esse procedimento invalida sessões estudantis e QR Codes anteriores. Oriente o estudante a não compartilhar código, senha nem capturas do QR.
- Na devolução, o servidor registra a assinatura título por título. A devolução só fica disponível depois da entrega.
- Use **Exportar PDF** e escolha **Salvar como PDF** no diálogo de impressão do navegador. O termo inclui o registro de cada assinatura já feita e os espaços ainda pendentes.
- Na tela **Estudantes**, use **Exportar backup anual** para reunir em um único PDF todos os termos do ano letivo atual com o status de entrega/devolução vigente. No diálogo de impressão, selecione **Salvar como PDF**; cada termo começa em uma nova página. Estudantes concluídos em anos anteriores, sem termo no ciclo atual, não são incluídos.

Exemplo de CSV (UTF-8, cabeçalhos na primeira linha):

```csv
matricula;nome;turma
202612345;Ana da Silva;1º
202612346;João Souza;2º ano
```

Cada ano letivo tem seu próprio termo. Ao iniciar um novo ano, estudantes ativos são promovidos automaticamente (1º→2º e 2º→3º); quem concluiu o 3º ano fica arquivado, sem novo termo ativo. O ciclo, a turma histórica e a relação de títulos de cada termo ficam preservados, e é possível selecionar anos anteriores no detalhe do estudante e exportar o termo daquele ano em PDF.

Português e Matemática são específicos da turma e do ano letivo. Os outros 13 títulos são volumes únicos: um empréstimo ainda não devolvido acompanha o estudante nos ciclos seguintes, sem gerar uma nova assinatura de entrega. Títulos já devolvidos não são reemitidos automaticamente. Ao corrigir a turma no ciclo atual, os novos volumes anuais são acrescentados sem apagar assinaturas anteriores. Cada assinatura é registrada com data e hora; a devolução também guarda o e-mail do servidor autenticado.

O ano letivo é controlado por `SCHOOL_YEAR` (por padrão, o ano corrente). É possível defini-lo explicitamente no ambiente para ajustar o calendário escolar; a mudança para um ano posterior cria os ciclos e promoções faltantes na próxima inicialização do app. Não reduza o ano configurado depois que os ciclos futuros tiverem sido criados.

## Autenticação e usuários

O acesso usa conta e senha, com senha armazenada em hash e sessão protegida. A conta `fabricio.bizotto@ifc.edu.br` é promovida a administradora na inicialização do banco. Para criá-la no primeiro uso, execute `create-user` e informe esse e-mail; a senha não é criada automaticamente:

```powershell
docker compose run --rm web python server.py create-user
```

Administradores veem a seção **Usuários**, podem cadastrar contas `@ifc.edu.br`, promover servidores a administradores e ativar/desativar contas. Contas desativadas não podem entrar e sessões já abertas perdem o acesso na próxima requisição. O sistema impede que o administrador remova o próprio acesso pela interface ou que a última conta administradora ativa seja desativada/rebaixada. Não há cadastro público nem recuperação de senha implementados.

O botão Google permanece desativado: OAuth não está conectado até que o campus configure um provedor OIDC e suas credenciais e URLs de callback. Não publique este servidor diretamente na internet sem configurar esses controles e uma política de backup.

As assinaturas manuscritas são armazenadas como imagens junto às datas e ao registro do servidor. O QR autentica a sessão do estudante, mas não substitui a avaliação institucional sobre validade jurídica e requisitos de assinatura eletrônica. Validade jurídica e uso de credenciais por estudantes menores de idade devem ser avaliados pelo IFC antes do uso oficial.

## Privacidade

O aviso de privacidade está disponível publicamente em `/privacidade` e pelo link na tela de acesso e no rodapé da aplicação. Ele descreve os dados arquivados para controle interno, quem pode acessá-los, o contexto de estudantes adolescentes, serviços técnicos envolvidos e direitos dos titulares. Antes de usar dados reais em produção, o IFC deve validar o texto, definir e registrar a base legal e o prazo de retenção e inserir o canal institucional atualizado do encarregado de dados pessoais.

## Verificações

```powershell
python -m unittest
```
