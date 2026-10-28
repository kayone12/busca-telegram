import asyncio
import os
import pandas as pd
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelPrivateError

# --- CONFIGURAÇÕES ---
API_ID = 37979718
API_HASH = 'ed249b9948a6eccc286fde372fc8a64a'
NOME_DO_GRUPO = 'COMPROV'

DELAY_ENTRE_BUSCAS = 2.0
ANO_FILTRO = 2026
# ---------------------

PASTA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CLIENTES = os.path.join(PASTA_SCRIPT, 'clientes.xlsx')
ARQUIVO_SESSAO = os.path.join(PASTA_SCRIPT, 'sessao_telegram.session')
ARQUIVO_LOG = os.path.join(PASTA_SCRIPT, 'debug_log.txt')


def gerar_variacoes_telefone(numero):
    variacoes = set()
    limpo = ''.join(c for c in str(numero) if c.isdigit() or c == '+')
    if not limpo:
        return []
    variacoes.add(limpo)
    if limpo.startswith('+55'):
        variacoes.add(limpo[3:])
        variacoes.add(limpo[1:])
    elif limpo.startswith('55'):
        variacoes.add(limpo[2:])
        variacoes.add('+' + limpo)
    elif limpo.startswith('+'):
        variacoes.add(limpo[1:])
    else:
        variacoes.add('55' + limpo)
        variacoes.add('+55' + limpo)
    variacoes.discard('')
    return list(variacoes)


def normalizar_numero_planilha(numero):
    if pd.isna(numero):
        return ''
    if pd.api.types.is_number(numero) and float(numero).is_integer():
        return str(int(numero))
    return str(numero).strip()


async def escrever_log(mensagem):
    with open(ARQUIVO_LOG, 'a', encoding='utf-8') as f:
        f.write(mensagem + '\n')
    print(mensagem)


async def rodar_verificacao():
    # Limpa log anterior
    if os.path.exists(ARQUIVO_LOG):
        os.remove(ARQUIVO_LOG)

    # Lê a planilha completa
    try:
        df = pd.read_excel(ARQUIVO_CLIENTES)
    except FileNotFoundError:
        print(f"❌ ERRO: 'clientes.xlsx' não encontrado em:\n{ARQUIVO_CLIENTES}")
        return
    except Exception as e:
        print(f"❌ ERRO ao ler planilha: {e}")
        return

    # Normaliza números importados como float pelo Excel antes de filtrar e buscar.
    df['Numero do whatsapp'] = df['Numero do whatsapp'].map(normalizar_numero_planilha)
    df = df[df['Numero do whatsapp'] != '']
    df = df.reset_index(drop=True)

    total_validos = len(df)
    print(f"📋 Após remover linhas vazias, sobraram {total_validos} números válidos.\n")

    if total_validos == 0:
        print("❌ Não há números válidos na planilha.")
        return

    # Pergunta quantos quer rodar agora
    while True:
        limite_input = input(f"Quantos números deseja processar? (máximo {total_validos}, ou 'todos'): ").strip()
        if limite_input.lower() == 'todos':
            LIMITE = total_validos
            break
        try:
            LIMITE = int(limite_input)
            if LIMITE <= 0:
                print("Digite um número maior que zero.")
                continue
            if LIMITE > total_validos:
                print(f"Só existem {total_validos} números válidos. Digite um número menor ou igual.")
                continue
            break
        except ValueError:
            print("Digite um número válido ou 'todos'.")

    # Pega apenas os primeiros LIMITE números válidos
    df = df.head(LIMITE)
    print(f"⚠️  Processando os primeiros {LIMITE} números válidos.\n")

    # Nome do arquivo com data E hora
    AGORA = datetime.now().strftime('%Y-%m-%d_%H-%M')
    ARQUIVO_SAIDA = os.path.join(PASTA_SCRIPT, f'Resultado_Verificacao_{AGORA}.xlsx')

    encontrados = []
    nao_encontrados = []
    apenas_ano_filtro = []

    async with TelegramClient(ARQUIVO_SESSAO, API_ID, API_HASH) as client:
        try:
            me = await client.get_me()
            await escrever_log(f"✅ Logado como: {me.first_name} ({me.phone}) - ID: {me.id}\n")
        except Exception as e:
            await escrever_log(f"❌ ERRO: Não está logado no Telegram! Detalhe: {e}")
            return

        grupo = None
        try:
            async for dialog in client.iter_dialogs():
                if dialog.name == NOME_DO_GRUPO:
                    grupo = dialog.entity
                    await escrever_log(f"✅ Grupo encontrado: '{dialog.name}' (ID: {dialog.id})")
                    break
        except Exception as e:
            await escrever_log(f"❌ ERRO ao listar dialogs: {e}")

        if grupo is None:
            await escrever_log(f"❌ ERRO: Grupo '{NOME_DO_GRUPO}' NÃO foi encontrado!")
            await escrever_log("   Verifique se o nome está exato.\n")
            return

        await escrever_log(f"\n🔍 Iniciando busca de números...\n")

        for index, row in df.iterrows():
            numero_raw = row.get('Numero do whatsapp', '')
            usuario_raw = row.get('Usuario', '')
            usuario = '' if pd.isna(usuario_raw) else str(usuario_raw).strip()

            achou = None
            variacao_achou = None
            tipo_busca = ''

            print(f"[{index + 1}/{len(df)}] {numero_raw} ... ", end="")

            # 1. PRIMEIRO: tenta buscar pelo número
            variacoes = gerar_variacoes_telefone(numero_raw)
            for var in variacoes:
                try:
                    mensagens = await client.get_messages(grupo, search=var, limit=5)
                    if mensagens:
                        achou = mensagens[0]
                        variacao_achou = var
                        tipo_busca = 'Numero'
                        break
                except FloodWaitError as e:
                    await escrever_log(f"\n⏳ FloodWait: esperar {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                    continue
                except ChannelPrivateError:
                    break
                except Exception as e:
                    continue

                await asyncio.sleep(0.5)

            # 2. SE não achou pelo número, tenta buscar pelo USUÁRIO
            if not achou and usuario and usuario.lower() != 'nan':
                print(f"(não achou por número, tentando usuário '{usuario}') ... ", end="")
                try:
                    mensagens = await client.get_messages(grupo, search=usuario, limit=5)
                    if mensagens:
                        achou = mensagens[0]
                        variacao_achou = usuario
                        tipo_busca = 'Usuario'
                except FloodWaitError as e:
                    await escrever_log(f"\n⏳ FloodWait: esperar {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                except ChannelPrivateError:
                    pass
                except Exception as e:
                    await escrever_log(f"\n⚠️  Erro ao buscar usuário '{usuario}': {e}")

            if achou:
                texto_msg = (achou.message or "")[:80].replace('\n', ' ')
                data = achou.date.strftime('%d/%m/%Y %H:%M:%S')
                ano_mensagem = achou.date.year

                encontrados.append({
                    'Numero do whatsapp': numero_raw,
                    'Usuario': usuario,
                    'Ultimo Registro': data,
                    'Variacao Busca': variacao_achou,
                    'Tipo Busca': tipo_busca,
                    'Trecho Mensagem': texto_msg
                })

                if ano_mensagem == ANO_FILTRO:
                    apenas_ano_filtro.append({
                        'Numero do whatsapp': numero_raw,
                        'Usuario': usuario,
                        'Ultimo Registro': data,
                        'Variacao Busca': variacao_achou,
                        'Tipo Busca': tipo_busca,
                        'Trecho Mensagem': texto_msg
                    })

                print(f"🟢 ACHOU via {tipo_busca} ('{variacao_achou}') | {data} | '{texto_msg}...'")
                await escrever_log(f"✅ {numero_raw} (Usuário: {usuario}) -> ACHOU via {tipo_busca}: '{variacao_achou}' | {data} | Ano: {ano_mensagem}")
            else:
                nao_encontrados.append({
                    'Numero do whatsapp': numero_raw,
                    'Usuario': usuario,
                    'Ultimo Registro': 'Sem registro',
                    'Variacao Busca': ', '.join(variacoes[:3]) + (f" | Usuario: {usuario}" if usuario else ""),
                    'Tipo Busca': '-',
                    'Erro': 'Nenhuma mensagem encontrada por número nem por usuário'
                })
                print("🔴 Não encontrado (nem por número, nem por usuário)")
                await escrever_log(f"❌ {numero_raw} (Usuário: {usuario}) -> NÃO achou por número nem por usuário")

            await asyncio.sleep(DELAY_ENTRE_BUSCAS)

    # Salva resultado em 3 abas
    try:
        with pd.ExcelWriter(ARQUIVO_SAIDA, engine='openpyxl') as writer:
            pd.DataFrame(encontrados).to_excel(writer, sheet_name='Com Registro', index=False)
            pd.DataFrame(nao_encontrados).to_excel(writer, sheet_name='Sem Registro', index=False)
            pd.DataFrame(apenas_ano_filtro).to_excel(writer, sheet_name=f'Apenas {ANO_FILTRO}', index=False)
        print(f"\n✅ Concluído! Salvo em:\n{ARQUIVO_SAIDA}")
        print(f"   📊 Com registro: {len(encontrados)} | Sem registro: {len(nao_encontrados)} | Apenas {ANO_FILTRO}: {len(apenas_ano_filtro)}")
        print(f"\n📋 Log detalhado em: {ARQUIVO_LOG}")
    except Exception as e:
        print(f"\n❌ ERRO ao salvar: {e}")


asyncio.run(rodar_verificacao())