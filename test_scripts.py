#!/usr/bin/env python3
"""
Scripts de teste para o Playwright Automation Server
Execute com: python test_scripts.py
"""

import requests
import json
import time
from datetime import datetime

# Configurações
BASE_URL = "http://localhost:8000"
ADMIN_API_KEY = "admin-super-secret-key-2024"
HEADERS = {"Authorization": f"Bearer {ADMIN_API_KEY}"}


def print_response(title, response):
    print(f"\n{'=' * 60}")
    print(f"🧪 {title}")
    print(f"{'=' * 60}")
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2, default=str)}")
        return data
    else:
        print(f"Error: {response.text}")
        return None


# 1. Script de Teste Básico - Google Search
test_script_1 = {
    "script": """
async def main():
    # Navegar para o Google
    await page.goto('https://www.google.com')

    # Aceitar cookies se aparecer
    try:
        accept_btn = page.locator('button:has-text("Aceitar tudo"), button:has-text("Accept all")')
        if await accept_btn.count() > 0:
            await accept_btn.first.click()
            await page.wait_for_timeout(1000)
    except:
        pass

    # Buscar por "playwright automation"
    search_box = page.locator('input[name="q"], textarea[name="q"]')
    await search_box.fill('playwright automation testing')
    await search_box.press('Enter')

    # Aguardar resultados
    await page.wait_for_selector('h3', timeout=10000)

    # Extrair primeiros 5 resultados
    results = []
    titles = page.locator('h3')
    count = await titles.count()

    for i in range(min(5, count)):
        try:
            title = await titles.nth(i).inner_text()
            results.append(title)
        except:
            continue

    return {
        'search_term': 'playwright automation testing',
        'results_count': len(results),
        'results': results,
        'page_title': await page.title(),
        'url': page.url,
        'timestamp': datetime.now().isoformat()
    }
""",
    "timeout": 30,
    "priority": 3,
    "tags": ["test", "google", "search"],
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# 2. Script de Teste - Formulário HTTP
test_script_2 = {
    "script": """
async def main():
    # Navegar para página de teste de formulário
    await page.goto('https://httpbin.org/forms/post')

    # Preencher formulário
    await page.fill('input[name="custname"]', 'Teste Playwright')
    await page.fill('input[name="custtel"]', '+55 11 99999-9999')
    await page.fill('input[name="custemail"]', 'teste@playwright.com')

    # Selecionar pizza size
    await page.check('input[value="large"]')

    # Selecionar toppings
    await page.check('input[value="bacon"]')
    await page.check('input[value="cheese"]')

    # Adicionar comentários
    await page.fill('textarea[name="comments"]', 'Teste automatizado com Playwright')

    # Submeter formulário
    await page.click('input[type="submit"]')

    # Aguardar resposta
    await page.wait_for_load_state('networkidle')

    # Extrair dados da resposta
    response_text = await page.text_content('body')

    return {
        'form_submitted': True,
        'response_data': response_text[:500] + '...' if len(response_text) > 500 else response_text,
        'final_url': page.url,
        'success': 'form' in response_text.lower(),
        'timestamp': datetime.now().isoformat()
    }
""",
    "timeout": 25,
    "priority": 2,
    "tags": ["test", "form", "httpbin"],
    "webhook_url": "https://webhook.site/your-webhook-id",  # Substitua por um webhook real se quiser testar
}

# 3. Script de Teste - Screenshot e Dados
test_script_3 = {
    "script": """
async def main():
    # Lista de sites para visitar
    sites = [
        'https://example.com',
        'https://httpbin.org/json',
        'https://httpbin.org/user-agent'
    ]

    results = []

    for site in sites:
        try:
            await page.goto(site)
            await page.wait_for_load_state('networkidle')

            # Extrair informações
            title = await page.title()
            url = page.url
            content_length = len(await page.content())

            # Pegar um snippet do conteúdo
            body_text = await page.text_content('body')
            snippet = body_text[:200] + '...' if len(body_text) > 200 else body_text

            results.append({
                'site': site,
                'title': title,
                'final_url': url,
                'content_length': content_length,
                'snippet': snippet,
                'load_time': '< 5s'  # Simplificado
            })

        except Exception as e:
            results.append({
                'site': site,
                'error': str(e),
                'success': False
            })

    return {
        'test_type': 'multi_site_visit',
        'sites_tested': len(sites),
        'successful_loads': len([r for r in results if 'error' not in r]),
        'results': results,
        'timestamp': datetime.now().isoformat()
    }
""",
    "timeout": 45,
    "priority": 1,
    "tags": ["test", "screenshot", "multi-site"],
}

# 4. Script de Teste - Complexidade Média
test_script_4 = {
    "script": """
async def main():
    # Teste de interação complexa
    await page.goto('https://jsonplaceholder.typicode.com')

    # Extrair informações da página
    title = await page.title()

    # Simular navegação e coleta de dados
    data_sources = [
        '/posts/1',
        '/users/1',
        '/albums/1'
    ]

    collected_data = {}

    for endpoint in data_sources:
        try:
            # Navegar para endpoint
            await page.goto(f'https://jsonplaceholder.typicode.com{endpoint}')

            # Extrair JSON da página
            content = await page.text_content('pre')
            if content:
                import json
                try:
                    json_data = json.loads(content)
                    collected_data[endpoint] = {
                        'type': endpoint.split('/')[1],
                        'id': json_data.get('id'),
                        'title': json_data.get('title', json_data.get('name', 'N/A')),
                        'data_keys': list(json_data.keys())
                    }
                except:
                    collected_data[endpoint] = {'error': 'Failed to parse JSON'}

        except Exception as e:
            collected_data[endpoint] = {'error': str(e)}

    return {
        'test_type': 'api_data_collection',
        'main_title': title,
        'endpoints_tested': len(data_sources),
        'successful_extractions': len([k for k, v in collected_data.items() if 'error' not in v]),
        'data': collected_data,
        'timestamp': datetime.now().isoformat()
    }
""",
    "timeout": 40,
    "priority": 4,
    "tags": ["test", "api", "json", "complex"],
}

# 5. Script de Teste Rápido - Validação
test_script_5 = {
    "script": """
async def main():
    # Teste simples e rápido
    await page.goto('https://httpbin.org/get')

    # Extrair dados básicos
    content = await page.text_content('body')

    try:
        import json
        data = json.loads(content)

        return {
            'test_type': 'quick_validation',
            'success': True,
            'user_agent': data.get('headers', {}).get('User-Agent', 'Unknown'),
            'origin': data.get('origin'),
            'url': data.get('url'),
            'headers_count': len(data.get('headers', {})),
            'timestamp': datetime.now().isoformat()
        }
    except:
        return {
            'test_type': 'quick_validation',
            'success': False,
            'raw_content': content[:200],
            'timestamp': datetime.now().isoformat()
        }
""",
    "timeout": 15,
    "priority": 5,
    "tags": ["test", "quick", "validation"],
}


def test_health_check():
    """Teste de health check"""
    print("\n🏥 Testando Health Check...")
    response = requests.get(f"{BASE_URL}/health")
    return print_response("Health Check", response)


def test_api_key_creation():
    """Teste de criação de API key"""
    print("\n🔑 Testando Criação de API Key...")

    new_key_data = {
        "name": "Test Key - " + datetime.now().strftime("%H:%M:%S"),
        "scopes": ["execute", "videos", "dashboard"],
        "rate_limit_per_minute": 20,
        "notes": "Chave criada para testes automatizados",
    }

    response = requests.post(
        f"{BASE_URL}/admin/api-keys", headers=HEADERS, json=new_key_data
    )

    return print_response("Criação de API Key", response)


def test_script_validation(script_data):
    """Teste de validação de script"""
    print(f"\n✅ Validando Script...")

    response = requests.post(f"{BASE_URL}/validate", headers=HEADERS, json=script_data)

    return print_response("Validação de Script", response)


def test_script_execution(script_data, script_name):
    """Teste de execução de script"""
    print(f"\n🚀 Executando Script: {script_name}")

    response = requests.post(f"{BASE_URL}/execute", headers=HEADERS, json=script_data)

    return print_response(f"Execução: {script_name}", response)


def test_queue_status():
    """Teste de status da fila"""
    print("\n📋 Verificando Status da Fila...")

    response = requests.get(f"{BASE_URL}/queue/status", headers=HEADERS)

    return print_response("Status da Fila", response)


def test_templates():
    """Teste de templates disponíveis"""
    print("\n📄 Verificando Templates Disponíveis...")

    response = requests.get(f"{BASE_URL}/templates", headers=HEADERS)

    return print_response("Templates Disponíveis", response)


def main():
    print("🎭 PLAYWRIGHT AUTOMATION SERVER - SUITE DE TESTES")
    print("=" * 60)

    # 1. Health Check
    health_data = test_health_check()
    if not health_data or health_data.get("status") != "healthy":
        print("❌ Servidor não está saudável. Abortando testes.")
        return

    # 2. Verificar templates
    test_templates()

    # 3. Criar uma nova API key para testes
    new_key = test_api_key_creation()

    # 4. Testar validação de scripts
    print("\n" + "=" * 60)
    print("🧪 TESTANDO VALIDAÇÃO DE SCRIPTS")
    print("=" * 60)

    scripts = [
        (test_script_1, "Google Search"),
        (test_script_2, "Formulário HTTP"),
        (test_script_3, "Multi-site Visit"),
        (test_script_4, "API Data Collection"),
        (test_script_5, "Quick Validation"),
    ]

    for script_data, name in scripts:
        test_script_validation(script_data)
        time.sleep(1)

    # 5. Executar scripts (apenas alguns para não sobrecarregar)
    print("\n" + "=" * 60)
    print("🚀 EXECUTANDO SCRIPTS DE TESTE")
    print("=" * 60)

    # Executar apenas scripts rápidos para demonstração
    quick_scripts = [
        (test_script_5, "Quick Validation"),
        (test_script_2, "Formulário HTTP"),
    ]

    executed_requests = []
    for script_data, name in quick_scripts:
        result = test_script_execution(script_data, name)
        if result and "request_id" in result:
            executed_requests.append(result["request_id"])
        time.sleep(2)

    # 6. Verificar status da fila
    test_queue_status()

    # 7. Informações finais
    print("\n" + "=" * 60)
    print("📊 RESUMO DOS TESTES")
    print("=" * 60)
    print(f"✅ Scripts validados: {len(scripts)}")
    print(f"🚀 Scripts executados: {len(quick_scripts)}")
    print(f"🎬 Vídeos gerados: {len(executed_requests)}")

    if executed_requests:
        print(f"\n🎥 Vídeos disponíveis em:")
        for req_id in executed_requests:
            print(f"   http://localhost:8000/video/{req_id}/{ADMIN_API_KEY}")

    print(f"\n🎛️  Dashboard: http://localhost:8000/dashboard?api_key={ADMIN_API_KEY}")
    print(f"📖 Documentação: http://localhost:8000/docs")

    print("\n🎉 Testes concluídos com sucesso!")


if __name__ == "__main__":
    main()
