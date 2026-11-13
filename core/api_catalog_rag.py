"""Módulo de Catálogo, Verificação em Lote (Health Check) e RAG de APIs Públicas e Governamentais.

Permite que os agentes (Diretor, Ponytail Dev, Concio, Designer) tenham conhecimento profundo
e acesso a endpoints públicos e governamentais para composição de sites, webapps, formulários,
dashboards e microsserviços.

Realiza checagem em lote, diagnóstico de latência e aplicação de alertas para APIs que
exigem autenticação ou parâmetros especiais, além de descartar rotas instáveis/fora do ar.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from core import rag_engine

ROOT = Path(__file__).resolve().parent.parent

# Definição canônica do catálogo de APIs públicas e governamentais
API_CATALOG: list[dict[str, Any]] = [
    {
        "id": "BR-UTIL-001",
        "name": "BrasilAPI",
        "category": "utilidade_brasil",
        "tags": "brasilapi cep cnpj bancos fipe taxas juros selic cdi feriados ddd receita endereco empresa",
        "base_url": "https://brasilapi.com.br/api",
        "doc_url": "https://brasilapi.com.br/docs",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://brasilapi.com.br/api/cep/v2/01001000",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/cep/v2/{cep}",
                "description": "Consulta de CEP com dados de logradouro, bairro, cidade, estado e coordenadas geográficas (lat/long) via fallback múltiplo.",
                "params": "cep (8 dígitos)",
            },
            {
                "method": "GET",
                "path": "/cnpj/v1/{cnpj}",
                "description": "Consulta cadastral unificada de CNPJ diretamente na base da Receita Federal (razão social, CNAE, sócios, situação).",
                "params": "cnpj (14 dígitos)",
            },
            {
                "method": "GET",
                "path": "/banks/v1",
                "description": "Lista completa e oficial de bancos no Brasil com códigos COMPE e ISPB.",
                "params": "nenhum",
            },
            {
                "method": "GET",
                "path": "/taxas/v1",
                "description": "Consulta taxas oficiais de juros e indicadores econômicos (Selic, CDI, IPCA).",
                "params": "nenhum",
            },
            {
                "method": "GET",
                "path": "/feriados/v1/{ano}",
                "description": "Lista de feriados nacionais oficiais para o ano fornecido.",
                "params": "ano (ex: 2026)",
            },
            {
                "method": "GET",
                "path": "/ddd/v1/{ddd}",
                "description": "Retorna o estado e todas as cidades correspondentes ao código DDD.",
                "params": "ddd (ex: 11)",
            },
        ],
        "use_case": "Preenchimento automático instantâneo de formulários de checkout e cadastro, validação de empresas B2B, seletores bancários e calendários de feriados.",
        "js_example": """// Autocompletar endereço por CEP via BrasilAPI
async function buscarCep(cep) {
  const res = await fetch(`https://brasilapi.com.br/api/cep/v2/${cep}`);
  if (!res.ok) throw new Error('CEP não encontrado');
  return await res.json(); // { street, neighborhood, city, state, location: { coordinates } }
}""",
        "py_example": """import httpx

def get_cnpj_info(cnpj: str) -> dict:
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}")
        r.raise_for_status()
        return r.json()""",
    },
    {
        "id": "BR-UTIL-002",
        "name": "ViaCEP",
        "category": "utilidade_brasil",
        "tags": "viacep cep endereco logradouro correios ibge siafi ddd preenchimento cadastro",
        "base_url": "https://viacep.com.br/ws/",
        "doc_url": "https://viacep.com.br",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://viacep.com.br/ws/01001000/json/",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/ws/{cep}/json/",
                "description": "Consulta de CEP retornando logradouro, complemento, bairro, localidade, UF, código IBGE e SIAFI.",
                "params": "cep (8 dígitos)",
            },
            {
                "method": "GET",
                "path": "/ws/{uf}/{cidade}/{logradouro}/json/",
                "description": "Pesquisa reversa de endereço por nome de rua ou logradouro.",
                "params": "uf (2 letras), cidade, logradouro",
            },
        ],
        "use_case": "Padrão de ouro e fallback número 1 para preenchimento de endereços em e-commerce e obtenção do código IBGE do município.",
        "js_example": """async function consultarViaCep(cep) {
  const cleanCep = cep.replace(/\\D/g, '');
  const r = await fetch(`https://viacep.com.br/ws/${cleanCep}/json/`);
  return await r.json(); // { logradouro, bairro, localidade, uf, ibge }
}""",
        "py_example": """import httpx

def consulta_viacep(cep: str) -> dict:
    clean = ''.join(filter(str.isdigit, cep))
    r = httpx.get(f"https://viacep.com.br/ws/{clean}/json/", timeout=5.0)
    return r.json()""",
    },
    {
        "id": "BR-UTIL-003",
        "name": "Minha Receita",
        "category": "utilidade_brasil",
        "tags": "minhareceita cnpj receita federal empresas socios qsa cnae razao social situacao cadastral",
        "base_url": "https://minhareceita.org",
        "doc_url": "https://minhareceita.org",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://minhareceita.org/00000000000191",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/{cnpj}",
                "description": "Consulta pública detalhada de CNPJ da Receita Federal: Razão Social, CNAE, Quadro de Sócios (QSA), capital e endereço.",
                "params": "cnpj (14 dígitos)",
            }
        ],
        "use_case": "Onboarding B2B, checagem de fornecedores e parceiros (KYS), validação de sócios e cálculo de risco cadastral.",
        "js_example": """async function consultarCnpj(cnpj) {
  const clean = cnpj.replace(/\\D/g, '');
  const res = await fetch(`https://minhareceita.org/${clean}`);
  return await res.json(); // { razao_social, cnae_fiscal_descricao, qsa, capital_social }
}""",
        "py_example": """import httpx

def get_empresa(cnpj: str) -> dict:
    clean = ''.join(filter(str.isdigit, cnpj))
    return httpx.get(f"https://minhareceita.org/{clean}", timeout=8.0).json()""",
    },
    {
        "id": "BR-GOV-004",
        "name": "IBGE Serviços de Dados",
        "category": "governo_estatistica",
        "tags": "ibge estados municipios cidades regioes censo estatistica demografia nomes populacao",
        "base_url": "https://servicodados.ibge.gov.br/api",
        "doc_url": "https://servicodados.ibge.gov.br/api/docs/",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://servicodados.ibge.gov.br/api/v1/localidades/estados",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/v1/localidades/estados",
                "description": "Relação de todas as 27 Unidades Federativas do Brasil com siglas, IDs e regiões.",
                "params": "nenhum",
            },
            {
                "method": "GET",
                "path": "/v1/localidades/estados/{uf}/municipios",
                "description": "Lista de todos os municípios de um determinado estado.",
                "params": "uf (ex: 35 para SP ou SP)",
            },
            {
                "method": "GET",
                "path": "/v2/censos/nomes/{nome}",
                "description": "Frequência e evolução histórica de prenomes masculinos e femininos no Brasil por décadas.",
                "params": "nome (ex: maria, joao)",
            },
        ],
        "use_case": "Seletores encadeados de Estado e Cidade em interfaces web, mapas demográficos, normalização de regiões e dados censitários.",
        "js_example": """async function carregarEstados() {
  const res = await fetch('https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome');
  return await res.json(); // [{ id, sigla, nome, regiao }]
}""",
        "py_example": """import httpx

def get_municipios_uf(uf_sigla: str) -> list[dict]:
    r = httpx.get(f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_sigla}/municipios", timeout=6.0)
    return r.json()""",
    },
    {
        "id": "BR-GOV-003",
        "name": "Banco Central do Brasil (Bacen / PTAX & SGS)",
        "category": "governo_financeiro",
        "tags": "bacen banco central ptax cotacao dolar euro selic ipca inflacao cambio moedas sgs",
        "base_url": "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata",
        "doc_url": "https://dadosabertos.bcb.gov.br",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/Moedas?$top=5&$format=json",
        "test_headers": {"Accept": "application/json"},
        "status": "healthy_with_notes",
        "requires_auth": False,
        "note": "Para séries diárias SGS (como Selic série 11), é OBRIGATÓRIO informar janela de data ou usar /dados/ultimos/{n} para evitar erro HTTP 406.",
        "endpoints": [
            {
                "method": "GET",
                "path": "/Moedas?$format=json",
                "description": "Lista de moedas estrangeiras disponíveis para consulta PTAX.",
                "params": "nenhum",
            },
            {
                "method": "GET",
                "path": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/{n}?formato=json",
                "description": "Últimos N registros da taxa Selic diária oficial.",
                "params": "n (quantidade de dias recentes, ex: 10)",
            },
            {
                "method": "GET",
                "path": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados/ultimos/{n}?formato=json",
                "description": "Últimos N registros mensais do IPCA (inflação oficial).",
                "params": "n (quantidade de meses, ex: 12)",
            },
        ],
        "use_case": "Conversão cambial oficial PTAX para contabilidade e e-commerce internacional, e reajuste automático de parcelas por Selic/IPCA.",
        "js_example": """async function getUltimasTaxasSelic(dias = 5) {
  const r = await fetch(`https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/${dias}?formato=json`);
  return await r.json(); // [{ data: "DD/MM/YYYY", valor: "0.050788" }]
}""",
        "py_example": """import httpx

def get_selic_recente(dias: int = 10) -> list[dict]:
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/{dias}?formato=json"
    headers = {"Accept": "application/json", "User-Agent": "DevMaster"}
    return httpx.get(url, headers=headers, timeout=6.0).json()""",
    },
    {
        "id": "BR-GOV-005",
        "name": "Câmara dos Deputados (Dados Abertos)",
        "category": "governo_legislativo",
        "tags": "camara deputados politicos leis votacoes proposicoes gastos reembolsos ceap legislativo",
        "base_url": "https://dadosabertos.camara.leg.br/api/v2",
        "doc_url": "https://dadosabertos.camara.leg.br/swagger/api.html",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://dadosabertos.camara.leg.br/api/v2/deputados?itens=2",
        "test_headers": {"Accept": "application/json"},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/deputados",
                "description": "Listagem nominal de deputados em exercício, partidos, estados e fotos oficiais.",
                "params": "nome, siglaUf, siglaPartido, itens (paginação)",
            },
            {
                "method": "GET",
                "path": "/proposicoes",
                "description": "Tramitação em tempo real de Projetos de Lei (PL), PECs e Medidas Provisórias.",
                "params": "siglaTipo, numero, ano",
            },
            {
                "method": "GET",
                "path": "/deputados/{id}/despesas",
                "description": "Detalhamento e notas fiscais de gastos da cota parlamentar (CEAP).",
                "params": "id (ID do deputado), ano, mes",
            },
        ],
        "use_case": "Aplicações de monitoramento de risco regulatório, jornalismo de dados, bots cívicos de transparência e portais de políticas públicas.",
        "js_example": """async function listarDeputados(uf = 'SP') {
  const r = await fetch(`https://dadosabertos.camara.leg.br/api/v2/deputados?siglaUf=${uf}&itens=10`);
  return await r.json(); // { dados: [{ id, nome, siglaPartido, urlFoto }] }
}""",
        "py_example": """import httpx

def get_deputados(uf: str = "RJ") -> list[dict]:
    r = httpx.get(f"https://dadosabertos.camara.leg.br/api/v2/deputados?siglaUf={uf}&itens=15", timeout=8.0)
    return r.json().get("dados", [])""",
    },
    {
        "id": "PUB-WEATHER-001",
        "name": "Open-Meteo Weather API",
        "category": "clima_tempo",
        "tags": "clima tempo temperatura previsao chuva vento meteorological weather openmeteo",
        "base_url": "https://api.open-meteo.com/v1",
        "doc_url": "https://open-meteo.com/en/docs",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://api.open-meteo.com/v1/forecast?latitude=-23.55&longitude=-46.63&current_weather=true",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/forecast",
                "description": "Previsão do tempo horária e diária global sem necessidade de API key.",
                "params": "latitude, longitude, current_weather=true, hourly=temperature_2m",
            }
        ],
        "use_case": "Widgets de clima para portais, dashboards corporativos, logística agrícola e eventos ao ar livre.",
        "js_example": """async function getClima(lat, lon) {
  const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current_weather=true`);
  return await r.json(); // { current_weather: { temperature, windspeed, weathercode } }
}""",
        "py_example": """import httpx

def get_weather(lat: float, lon: float) -> dict:
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    return httpx.get(url, timeout=6.0).json()["current_weather"]""",
    },
    {
        "id": "PUB-MOCK-001",
        "name": "JSONPlaceholder",
        "category": "mock_prototipagem",
        "tags": "mock prototipagem fake rest posts users comments placeholder json",
        "base_url": "https://jsonplaceholder.typicode.com",
        "doc_url": "https://jsonplaceholder.typicode.com",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://jsonplaceholder.typicode.com/posts/1",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET/POST/PUT/DELETE",
                "path": "/posts",
                "description": "Coleção mock de posts para prototipagem de feeds e blogs.",
                "params": "nenhum ou id",
            },
            {
                "method": "GET",
                "path": "/users",
                "description": "Lista mock com 10 usuários completos (nome, email, endereço, empresa).",
                "params": "nenhum",
            },
        ],
        "use_case": "Prototipagem rápida de layouts no Onlook, testes de front-end com dados simulados e scaffolding de componentes sem backend pronto.",
        "js_example": """async function getMockUsers() {
  const res = await fetch('https://jsonplaceholder.typicode.com/users');
  return await res.json(); // [{ id, name, email, company }]
}""",
        "py_example": """import httpx

def get_mock_posts() -> list[dict]:
    return httpx.get("https://jsonplaceholder.typicode.com/posts?_limit=5", timeout=5.0).json()""",
    },
    {
        "id": "PUB-DEV-001",
        "name": "GitHub REST API Pública",
        "category": "ferramentas_dev",
        "tags": "github repositorios usuarios dev commits releases gists codigo",
        "base_url": "https://api.github.com",
        "doc_url": "https://docs.github.com/en/rest",
        "auth_type": "none_optional_token",
        "cors": True,
        "test_endpoint": "https://api.github.com/users/octocat",
        "test_headers": {"User-Agent": "DevMaster-Client"},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/users/{username}",
                "description": "Consulta perfil público de qualquer usuário ou organização do GitHub.",
                "params": "username",
            },
            {
                "method": "GET",
                "path": "/repos/{owner}/{repo}",
                "description": "Metadados públicos de repositório (estrelas, forks, issues abertas).",
                "params": "owner, repo",
            },
        ],
        "use_case": "Dashboards de desenvolvedor, integração com Gitea/GitHub, checagem de portfólio de engenharia e métricas de repositório.",
        "js_example": """async function getGithubUser(username) {
  const r = await fetch(`https://api.github.com/users/${username}`, {
    headers: { 'User-Agent': 'DevMaster' }
  });
  return await r.json(); // { login, public_repos, followers, avatar_url }
}""",
        "py_example": """import httpx

def get_repo_stars(owner: str, repo: str) -> int:
    r = httpx.get(f"https://api.github.com/repos/{owner}/{repo}", headers={"User-Agent": "DevMaster"}, timeout=6.0)
    return r.json().get("stargazers_count", 0)""",
    },
    {
        "id": "PUB-GEO-001",
        "name": "Ipify IP Lookup",
        "category": "utilidade_global",
        "tags": "ip ipify rede conexao cliente auditoria ipv4 ipv6",
        "base_url": "https://api.ipify.org",
        "doc_url": "https://www.ipify.org",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://api.ipify.org?format=json",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/?format=json",
                "description": "Retorna o endereço IP público de saída do requisitante.",
                "params": "format=json",
            }
        ],
        "use_case": "Auditoria de segurança, logging LGPD de conexões de clientes e diagnóstico de rede.",
        "js_example": """async function getClientIp() {
  const r = await fetch('https://api.ipify.org?format=json');
  return (await r.json()).ip;
}""",
        "py_example": """import httpx

def get_public_ip() -> str:
    return httpx.get("https://api.ipify.org?format=json", timeout=4.0).json()["ip"]""",
    },
    {
        "id": "PUB-DEV-002",
        "name": "APIs.guru Directory",
        "category": "ferramentas_dev",
        "tags": "apis guru swagger openapi catalogo especificacoes rest schemas contratos",
        "base_url": "https://api.apis.guru/v2",
        "doc_url": "https://apis.guru",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://api.apis.guru/v2/list.json",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/list.json",
                "description": "Diretório de definições OpenAPI 2.0 / 3.0 de milhares de serviços globais.",
                "params": "nenhum",
            }
        ],
        "use_case": "Geração automatizada de clientes de código (SDKs), automação de validação de schemas OpenAPI e orquestração de rotas.",
        "js_example": """async function getApiSpecsList() {
  const r = await fetch('https://api.apis.guru/v2/list.json');
  return await r.json();
}""",
        "py_example": """import httpx

def list_openapis() -> dict:
    return httpx.get("https://api.apis.guru/v2/list.json", timeout=10.0).json()""",
    },
    {
        "id": "PUB-DEMO-001",
        "name": "Agify.io",
        "category": "utilidade_global",
        "tags": "agify predicao idade estimativa nome estatistica demo",
        "base_url": "https://api.agify.io",
        "doc_url": "https://agify.io",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://api.agify.io?name=michael",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/?name={nome}",
                "description": "Estima a idade provável de uma pessoa com base em amostras globais do prenome.",
                "params": "name, country_id",
            }
        ],
        "use_case": "Enriquecimento demográfico leve para demonstrações de inteligência de produto e dashboards.",
        "js_example": """async function estimarIdade(nome) {
  const r = await fetch(`https://api.agify.io?name=${encodeURIComponent(nome)}`);
  return await r.json(); // { name, age, count }
}""",
        "py_example": """import httpx

def get_estimated_age(name: str) -> int | None:
    return httpx.get(f"https://api.agify.io?name={name}", timeout=5.0).json().get("age")""",
    },
    {
        "id": "PUB-DEMO-002",
        "name": "Nationalize.io",
        "category": "utilidade_global",
        "tags": "nationalize nacionalidade pais probabilidade nome demo",
        "base_url": "https://api.nationalize.io",
        "doc_url": "https://nationalize.io",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://api.nationalize.io?name=nathaniel",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/?name={nome}",
                "description": "Calcula a probabilidade de nacionalidade e países de origem de um prenome.",
                "params": "name",
            }
        ],
        "use_case": "Normalização de idiomas em interfaces multilíngues e predição de país de origem.",
        "js_example": """async function estimarPais(nome) {
  const r = await fetch(`https://api.nationalize.io?name=${encodeURIComponent(nome)}`);
  return await r.json(); // { country: [{ country_id: 'US', probability: 0.89 }] }
}""",
        "py_example": """import httpx

def get_top_country(name: str) -> str | None:
    data = httpx.get(f"https://api.nationalize.io?name={name}", timeout=5.0).json()
    countries = data.get("country", [])
    return countries[0]["country_id"] if countries else None""",
    },
    {
        "id": "PUB-ENTERTAIN-001",
        "name": "Dog CEO API",
        "category": "midia_demo",
        "tags": "cachorro pet dog fotos imagens animais demo galeria",
        "base_url": "https://dog.ceo/api",
        "doc_url": "https://dog.ceo/dog-api/",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://dog.ceo/api/breeds/image/random",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/breeds/image/random",
                "description": "Retorna uma foto aleatória em alta resolução de cão.",
                "params": "nenhum",
            }
        ],
        "use_case": "Avatares, testes de layouts de cartões, galerias de e-commerce pet e testes visuais.",
        "js_example": """async function getDogImage() {
  const r = await fetch('https://dog.ceo/api/breeds/image/random');
  return (await r.json()).message; // url da imagem jpg
}""",
        "py_example": """import httpx

def get_random_dog_url() -> str:
    return httpx.get("https://dog.ceo/api/breeds/image/random", timeout=5.0).json()["message"]""",
    },
    {
        "id": "PUB-ENTERTAIN-002",
        "name": "CatFact Ninja",
        "category": "midia_demo",
        "tags": "gato cat curiosidades fatos pet entretenimento demo",
        "base_url": "https://catfact.ninja",
        "doc_url": "https://catfact.ninja",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://catfact.ninja/fact",
        "test_headers": {},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/fact",
                "description": "Retorna uma curiosidade aleatória sobre felinos em formato JSON.",
                "params": "max_length",
            }
        ],
        "use_case": "Tooltips dinâmicos, testes de componentes de cards informativos e placeholders divertidos.",
        "js_example": """async function getCatFact() {
  const r = await fetch('https://catfact.ninja/fact');
  return (await r.json()).fact;
}""",
        "py_example": """import httpx

def get_cat_fact() -> str:
    return httpx.get("https://catfact.ninja/fact", timeout=5.0).json()["fact"]""",
    },
    {
        "id": "PUB-ENTERTAIN-003",
        "name": "icanhazdadjoke",
        "category": "midia_demo",
        "tags": "piadas humor entretenimento dadjoke texto demo",
        "base_url": "https://icanhazdadjoke.com",
        "doc_url": "https://icanhazdadjoke.com/api",
        "auth_type": "none",
        "cors": True,
        "test_endpoint": "https://icanhazdadjoke.com/",
        "test_headers": {"Accept": "application/json", "User-Agent": "DevMaster"},
        "status": "healthy",
        "requires_auth": False,
        "endpoints": [
            {
                "method": "GET",
                "path": "/",
                "description": "Retorna uma piada no estilo 'tiozão' em JSON (requer header Accept: application/json).",
                "params": "nenhum",
            }
        ],
        "use_case": "Interações descontraídas para agentes de personalidade divertida (como Jorjão) e mocks de mensagens.",
        "js_example": """async function getDadJoke() {
  const r = await fetch('https://icanhazdadjoke.com/', {
    headers: { 'Accept': 'application/json' }
  });
  return (await r.json()).joke;
}""",
        "py_example": """import httpx

def get_dad_joke() -> str:
    headers = {"Accept": "application/json", "User-Agent": "DevMaster"}
    return httpx.get("https://icanhazdadjoke.com/", headers=headers, timeout=5.0).json()["joke"]""",
    },
    {
        "id": "BR-GOV-002",
        "name": "Portal da Transparência CGU",
        "category": "governo_auditoria",
        "tags": "cgu transparencia gastos publicos licitacoes contratos servidores bolsa familia alertas",
        "base_url": "https://api.portaldatransparencia.gov.br/api-de-dados",
        "doc_url": "https://api.portaldatransparencia.gov.br/swagger-ui.html",
        "auth_type": "api_key",
        "cors": True,
        "test_endpoint": "https://api.portaldatransparencia.gov.br/api-de-dados/licitacoes",
        "test_headers": {},
        "status": "alert_requires_auth",
        "requires_auth": True,
        "auth_header": "chave-api-rodada",
        "warning_message": "⚠️ ALERTA DE AUTENTICAÇÃO: Esta API requer cadastro gratuito no portal da CGU e inclusão do header 'chave-api-rodada' nas requisições. Não pode ser usada anonimamente.",
        "endpoints": [
            {
                "method": "GET",
                "path": "/licitacoes",
                "description": "Processos licitatórios federais por órgão, data ou município.",
                "params": "dataInicial, dataFinal, pagina",
            },
            {
                "method": "GET",
                "path": "/contratos",
                "description": "Contratos da União e valores empenhados.",
                "params": "numero, orgao, pagina",
            },
        ],
        "use_case": "Compliance corporativo, auditoria de licitações públicas e checagem de fornecedores inidôneos (CEIS).",
        "js_example": """async function consultarLicitacoes(chaveCgu) {
  const res = await fetch('https://api.portaldatransparencia.gov.br/api-de-dados/licitacoes?pagina=1', {
    headers: { 'chave-api-rodada': chaveCgu }
  });
  return await res.json();
}""",
        "py_example": """import httpx

def get_licitacoes(api_key: str) -> list[dict]:
    headers = {"chave-api-rodada": api_key}
    r = httpx.get("https://api.portaldatransparencia.gov.br/api-de-dados/licitacoes?pagina=1", headers=headers, timeout=10.0)
    return r.json()""",
    },
    {
        "id": "BR-GOV-001",
        "name": "Portal de Dados Abertos (dados.gov.br)",
        "category": "governo_catalogo",
        "tags": "dados.gov.br ckan datasets catalogo governo federal conjuntos dados alertas",
        "base_url": "https://dados.gov.br/api/3/action",
        "doc_url": "https://dados.gov.br",
        "auth_type": "oauth_token",
        "cors": True,
        "test_endpoint": "https://dados.gov.br/api/3/action/package_search?q=saude&rows=1",
        "test_headers": {},
        "status": "alert_requires_auth",
        "requires_auth": True,
        "warning_message": "⚠️ ALERTA DE AUTENTICAÇÃO: O endpoint do barramento CKAN do dados.gov.br retornou HTTP 401 e foi migrado para o Gov.br Gateway. Requer token de autenticação prévio.",
        "endpoints": [
            {
                "method": "GET",
                "path": "/package_search?q={query}",
                "description": "Busca textual de pacotes de dados abertos governamentais.",
                "params": "q, rows",
            }
        ],
        "use_case": "Localização de datasets públicos governamentais (CSV/Parquet) de saúde, educação e orçamento federal.",
        "js_example": """// Requer token Gov.br após migração do portal
async function buscarDataset(query, token) {
  const r = await fetch(`https://dados.gov.br/api/3/action/package_search?q=${query}`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  return await r.json();
}""",
        "py_example": """import httpx

def search_dados_gov(query: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    return httpx.get(f"https://dados.gov.br/api/3/action/package_search?q={query}", headers=headers, timeout=10.0).json()""",
    },
    {
        "id": "DESCARTADA-001",
        "name": "Public APIs RAW (api.publicapis.org)",
        "category": "descartadas",
        "tags": "publicapis descontinuada fora do ar descartada",
        "base_url": "https://api.publicapis.org",
        "doc_url": "https://github.com/public-apis/public-apis",
        "auth_type": "none",
        "cors": False,
        "test_endpoint": "https://api.publicapis.org/entries",
        "test_headers": {},
        "status": "deprecated_down",
        "requires_auth": False,
        "warning_message": "❌ DESCARTADA / FORA DO AR: O domínio api.publicapis.org foi descontinuado e não resolve DNS (getaddrinfo failed). O repositório oficial no GitHub (github.com/public-apis/public-apis) permanece ativo como referência documental.",
        "endpoints": [],
        "use_case": "NÃO UTILIZAR EM PRODUÇÃO. Utilizar APIs.guru ou repositórios locais como alternativa.",
        "js_example": "// Rota descontinuada - Não utilizar",
        "py_example": "# Rota descontinuada - Não utilizar",
    },
    {
        "id": "DESCARTADA-002",
        "name": "CoinDesk BPI Legacy",
        "category": "descartadas",
        "tags": "coindesk bpi bitcoin cripto descontinuada fora do ar descartada",
        "base_url": "https://api.coindesk.com/v1/bpi",
        "doc_url": "https://www.coindesk.com",
        "auth_type": "none",
        "cors": False,
        "test_endpoint": "https://api.coindesk.com/v1/bpi/currentprice.json",
        "test_headers": {},
        "status": "deprecated_down",
        "requires_auth": False,
        "warning_message": "❌ DESCARTADA: O endpoint legado de BPI da CoinDesk foi descontinuado (DNS/Rota inacessível). Para dados de câmbio oficial e cripto, utilize o Bacen PTAX ou AwesomeAPI.",
        "endpoints": [],
        "use_case": "NÃO UTILIZAR EM PRODUÇÃO. Utilizar Bacen PTAX ou provedores alternativos.",
        "js_example": "// Rota descontinuada - Não utilizar",
        "py_example": "# Rota descontinuada - Não utilizar",
    },
]


async def check_single_api(api_data: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    """Testa uma API individual de forma assíncrona, medindo latência e identificando falhas."""
    test_url = api_data.get("test_endpoint") or api_data.get("base_url")
    headers = api_data.get("test_headers", {})
    if "User-Agent" not in headers:
        headers = {**headers, "User-Agent": "DevMaster-HealthChecker/3.0"}

    # Se já é marcada como descontinuada propositalmente, checamos rapidamente com fallback de erro
    is_deprecated = api_data.get("status") == "deprecated_down"

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(test_url, headers=headers)
            latency = round((time.perf_counter() - start) * 1000, 1)

            status_code = resp.status_code
            # Se for 2xx ou 3xx, é saudável
            is_healthy = 200 <= status_code < 400

            # Caso especial: CGU e Dados.gov.br retornam 401 por exigirem autenticação, mas o endpoint está online
            if status_code in (401, 403) and api_data.get("requires_auth"):
                final_status = "alert_requires_auth"
                diag = f"Online (HTTP {status_code}) - Exige credencial/header autorizado."
            elif is_healthy:
                final_status = "healthy"
                diag = f"Estável (HTTP {status_code}) - Resposta em {latency}ms."
            else:
                final_status = "failed"
                diag = f"Falha (HTTP {status_code}) - Erro na resposta."

            return {
                "id": api_data["id"],
                "name": api_data["name"],
                "url": test_url,
                "status_code": status_code,
                "latency_ms": latency,
                "is_healthy": is_healthy,
                "status": final_status,
                "diagnosis": diag,
                "error": None if is_healthy else f"HTTP {status_code}",
            }
    except Exception as exc:
        latency = round((time.perf_counter() - start) * 1000, 1)
        err_str = str(exc)
        if is_deprecated:
            diag = f"Descartada confirmada - Inacessível ({err_str[:40]})."
        else:
            diag = f"Erro de Conexão/Timeout ({err_str[:40]})."

        return {
            "id": api_data["id"],
            "name": api_data["name"],
            "url": test_url,
            "status_code": 0,
            "latency_ms": latency,
            "is_healthy": False,
            "status": "deprecated_down" if is_deprecated else "failed",
            "diagnosis": diag,
            "error": err_str[:80],
        }


async def batch_check_apis(timeout: float = 5.0) -> list[dict[str, Any]]:
    """Executa checagem de saúde em paralelo em todas as APIs do catálogo."""
    tasks = [check_single_api(api_item, timeout=timeout) for api_item in API_CATALOG]
    results = await asyncio.gather(*tasks)
    return list(results)


def format_rag_document(api_item: dict[str, Any], health_info: dict[str, Any] | None = None) -> str:
    """Gera um documento estruturado em Markdown otimizado para o RAG local."""
    h_status = "ESTÁVEL"
    h_diag = "Pronta para uso contínuo (CORS ativo, sem necessidade de chave)."
    h_lat = "Baixa"

    if health_info:
        lat = health_info.get("latency_ms", 0)
        h_lat = f"{lat}ms"
        if health_info.get("status") == "alert_requires_auth":
            h_status = "ALERTA (REQUER AUTENTICAÇÃO)"
            h_diag = health_info.get("diagnosis", "Exige chave de autenticação.")
        elif health_info.get("status") == "deprecated_down":
            h_status = "DESCARTADA (FORA DO AR)"
            h_diag = health_info.get("diagnosis", "Serviço descontinuado.")
        elif not health_info.get("is_healthy"):
            h_status = "FALHA / INSTÁVEL"
            h_diag = health_info.get("diagnosis", "Apresentou erro na checagem.")
    elif api_data_status := api_item.get("status"):
        if api_data_status == "alert_requires_auth":
            h_status = "ALERTA (REQUER AUTENTICAÇÃO)"
            h_diag = api_item.get("warning_message", "Exige chave.")
        elif api_data_status == "deprecated_down":
            h_status = "DESCARTADA (FORA DO AR)"
            h_diag = api_item.get("warning_message", "Descontinuada.")

    endpoints_md = ""
    for ep in api_item.get("endpoints", []):
        endpoints_md += f"- `{ep.get('method')} {ep.get('path')}`: {ep.get('description')} (Parâmetros: `{ep.get('params')}`)\n"

    warning_block = ""
    if api_item.get("warning_message"):
        warning_block = f"\n> [!WARNING]\n> {api_item['warning_message']}\n"
    elif api_item.get("note"):
        warning_block = f"\n> [!NOTE]\n> {api_item['note']}\n"

    doc = f"""# Especificação de API para Desenvolvimento: {api_item['name']} ({api_item['id']})

- **Categoria:** `{api_item['category']}`
- **URL Base:** `{api_item['base_url']}`
- **Autenticação:** `{api_item['auth_type']}` | **CORS Habilitado:** `{'Sim' if api_item.get('cors') else 'Não'}`
- **Status Operacional Auditado:** `{h_status}` (Latência: `{h_lat}`)
- **Diagnóstico:** {h_diag}
{warning_block}
### Endpoints e Recursos Oferecidos:
{endpoints_md or '- Endpoints descontinuados ou restritos.'}

### Caso de Uso Principal em Webapps / Sites / Agentes:
{api_item.get('use_case', 'Composição de sistemas e integração de dados.')}

### Snippet de Implementação no Frontend (JavaScript / TypeScript):
```javascript
{api_item.get('js_example', '// Exemplo não disponível')}
```

### Snippet de Implementação no Backend (Python httpx):
```python
{api_item.get('py_example', '# Exemplo não disponível')}
```
"""
    return doc


def ingest_api_catalog_to_rag(path: Path | None = None, health_map: dict[str, dict] | None = None) -> dict[str, int]:
    """Ingere todas as APIs no banco RAG (workspace/rag.db), com metadados de saúde e diagnóstico."""
    rag_engine.init_rag(path)
    inserted = 0
    updated = 0

    for api_item in API_CATALOG:
        api_id = api_item["id"]
        h_info = health_map.get(api_id) if health_map else None

        # Descartadas continuam indexadas com status 'descartada' e alerta explícito
        # para que os agentes saibam NÃO utilizá-las caso solicitadas pelo usuário!
        title = f"API Catalog: {api_item['name']} ({api_id})"
        content = format_rag_document(api_item, h_info)
        tags = f"api rest {api_item['category']} {api_item['tags']} {api_item.get('status')} {api_id.lower()}"

        doc_id = rag_engine.index_document(title, content, tags, path)
        if doc_id:
            inserted += 1

    return {"apis_indexed": inserted, "total_docs": rag_engine.stats(path)["docs"]}


def resolve_apis_for_task(task_or_prompt: str, limit: int = 3, path: Path | None = None) -> list[dict[str, Any]]:
    """Orquestrador de Seleção de APIs: Analisa a demanda da aplicação ou o prompt do usuário
    e retorna as APIs mais recomendadas e estáveis com código de exemplo e justificativa."""
    prompt_lower = task_or_prompt.lower()
    terms = rag_engine._terms(task_or_prompt)

    # 1. Regras heurísticas diretas para detecção de domínio
    score_map: dict[str, int] = {}
    for api_item in API_CATALOG:
        # Se for descartada, penalidade
        if api_item.get("status") == "deprecated_down":
            score_map[api_item["id"]] = -100
            continue

        score = 0
        tags = api_item.get("tags", "").lower()
        name = api_item.get("name", "").lower()

        # Heurísticas temáticas
        if any(w in prompt_lower for w in ("cep", "endereco", "endereço", "rua", "bairro", "correios")):
            if api_item["id"] in ("BR-UTIL-001", "BR-UTIL-002"):
                score += 50
        if any(w in prompt_lower for w in ("cnpj", "empresa", "empresar", "socio", "sócio", "receita", "cnae", "b2b")):
            if api_item["id"] in ("BR-UTIL-001", "BR-UTIL-003"):
                score += 50
        if any(w in prompt_lower for w in ("banco", "bancos", "pix", "ispb", "compe", "agencia", "conta")):
            if api_item["id"] == "BR-UTIL-001":
                score += 40
        if any(w in prompt_lower for w in ("taxa", "selic", "cdi", "ipca", "inflacao", "inflação", "cambio", "câmbio", "dolar", "dólar", "euro", "ptax")):
            if api_item["id"] in ("BR-GOV-003", "BR-UTIL-001"):
                score += 50
        if any(w in prompt_lower for w in ("estado", "cidade", "municipio", "município", "ibge", "regiao", "região", "demografia")):
            if api_item["id"] in ("BR-GOV-004", "BR-UTIL-001", "BR-UTIL-002"):
                score += 45
        if any(w in prompt_lower for w in ("clima", "tempo", "temperatura", "previsao", "previsão", "chuva", "weather")):
            if api_item["id"] == "PUB-WEATHER-001":
                score += 60
        if any(w in prompt_lower for w in ("mock", "placeholder", "teste", "fake", "prototipo", "protótipo", "posts", "feed")):
            if api_item["id"] == "PUB-MOCK-001":
                score += 50
        if any(w in prompt_lower for w in ("deputado", "politico", "político", "lei", "pl", "votacao", "votação", "camara", "câmara", "parlamentar")):
            if api_item["id"] == "BR-GOV-005":
                score += 60
        if any(w in prompt_lower for w in ("ip", "conexao", "geolocalizacao", "geolocalização", "ipify")):
            if api_item["id"] == "PUB-GEO-001":
                score += 50
        if any(w in prompt_lower for w in ("github", "repositorio", "repositório", "commit", "stars", "git")):
            if api_item["id"] == "PUB-DEV-001":
                score += 50
        if any(w in prompt_lower for w in ("swagger", "openapi", "schema", "contrato", "catalogo", "catálogo")):
            if api_item["id"] == "PUB-DEV-002":
                score += 40
        if any(w in prompt_lower for w in ("pet", "cachorro", "cao", "cão", "dog", "animais", "veterinaria")):
            if api_item["id"] == "PUB-ENTERTAIN-001":
                score += 50
        if any(w in prompt_lower for w in ("humor", "piada", "brincadeira", "dadjoke", "descontrair")):
            if api_item["id"] == "PUB-ENTERTAIN-003":
                score += 50

        # Term matching genérico
        for t in terms:
            if t in tags or t in name:
                score += 10

        score_map[api_item["id"]] = score

    # 2. Ordenar e selecionar os melhores
    sorted_ids = sorted([k for k, v in score_map.items() if v > 0], key=lambda k: score_map[k], reverse=True)

    # Se a heurística não pegou nada, faz busca via RAG FTS
    if not sorted_ids:
        fts_res = rag_engine.search(f"api {task_or_prompt}", limit=limit, path=path)
        rag_api_ids = []
        for r in fts_res:
            title = r.get("title", "")
            m = re.search(r"\(([A-Z0-9\-]+)\)", title)
            if m and m.group(1) in [a["id"] for a in API_CATALOG]:
                rag_api_ids.append(m.group(1))
        sorted_ids = rag_api_ids

    selected: list[dict[str, Any]] = []
    seen = set()
    for api_id in sorted_ids:
        if api_id in seen:
            continue
        api_obj = next((a for a in API_CATALOG if a["id"] == api_id), None)
        if api_obj and api_obj.get("status") != "deprecated_down":
            selected.append(api_obj)
            seen.add(api_id)
        if len(selected) >= limit:
            break

    # Se ainda estiver vazio e o usuário pediu explicitamente por apis, retorna as top públicas estáveis
    if not selected and any(w in prompt_lower for w in ("api", "apis", "dados", "integrar", "integracao", "integração")):
        selected = [a for a in API_CATALOG if a["id"] in ("BR-UTIL-001", "BR-UTIL-002", "PUB-WEATHER-001")][:limit]

    return selected

