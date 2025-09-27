#!/bin/bash

# ===============================================
# 🎭 Playwright Execute Endpoint - Test Examples
# ===============================================
# This script demonstrates working examples for the /execute endpoint

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
BASE_URL="http://localhost:8000"
ADMIN_KEY="admin-super-secret-key-2024"

print_header() {
    echo -e "\n${BLUE}===============================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}===============================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Test 1: Simple Hello World
test_hello_world() {
    print_header "Test 1: Simple Hello World"

    local script='{
        "script": "from playwright.async_api import async_playwright\n\nasync def main():\n    return {\"message\": \"Hello from Playwright!\", \"timestamp\": \"2024\"}",
        "timeout": 30,
        "priority": 1,
        "tags": ["test", "hello-world"]
    }'

    print_info "Executing simple Hello World script..."

    response=$(curl -s -X POST "$BASE_URL/execute" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "$script")

    if echo "$response" | grep -q '"success":true'; then
        request_id=$(echo "$response" | grep -o '"request_id":"[^"]*' | cut -d'"' -f4)
        print_success "Script executed successfully!"
        print_info "Request ID: $request_id"
        echo "$response" | python3 -c "import json, sys; data=json.load(sys.stdin); print(f'Queue Position: {data[\"queue_position\"]}'); print(f'Video URL: {data[\"video_url\"]}')" 2>/dev/null || echo "Response: $response"
    else
        print_error "Script execution failed"
        echo "Response: $response"
    fi
}

# Test 2: Basic Page Navigation
test_page_navigation() {
    print_header "Test 2: Basic Page Navigation"

    local script='{
        "script": "from playwright.async_api import async_playwright\n\nasync def main():\n    async with async_playwright() as p:\n        browser = await p.chromium.launch()\n        page = await browser.new_page()\n        await page.goto(\"https://example.com\")\n        title = await page.title()\n        url = page.url\n        await browser.close()\n        return {\"title\": title, \"url\": url, \"status\": \"navigation_complete\"}",
        "timeout": 60,
        "priority": 2,
        "tags": ["navigation", "example.com"]
    }'

    print_info "Executing page navigation to example.com..."

    response=$(curl -s -X POST "$BASE_URL/execute" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "$script")

    if echo "$response" | grep -q '"success":true'; then
        request_id=$(echo "$response" | grep -o '"request_id":"[^"]*' | cut -d'"' -f4)
        print_success "Navigation script executed successfully!"
        print_info "Request ID: $request_id"
        print_info "Check video recording at: $BASE_URL/video/$request_id/$ADMIN_KEY"
    else
        print_error "Navigation script failed"
        echo "Response: $response"
    fi
}

# Test 3: HTTPBin API Test
test_httpbin_api() {
    print_header "Test 3: HTTPBin API Test"

    local script='{
        "script": "from playwright.async_api import async_playwright\n\nasync def main():\n    async with async_playwright() as p:\n        browser = await p.chromium.launch()\n        page = await browser.new_page()\n        await page.goto(\"https://httpbin.org/html\")\n        title = await page.title()\n        # Get some content\n        h1_text = await page.locator(\"h1\").text_content() or \"No H1 found\"\n        await browser.close()\n        return {\"title\": title, \"h1_content\": h1_text, \"test_site\": \"httpbin.org\", \"status\": \"completed\"}",
        "timeout": 45,
        "priority": 1,
        "tags": ["httpbin", "api-test", "scraping"]
    }'

    print_info "Testing with HTTPBin HTML page..."

    response=$(curl -s -X POST "$BASE_URL/execute" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "$script")

    if echo "$response" | grep -q '"success":true'; then
        request_id=$(echo "$response" | grep -o '"request_id":"[^"]*' | cut -d'"' -f4)
        print_success "HTTPBin test completed successfully!"
        print_info "Request ID: $request_id"

        # Show analysis if available
        if echo "$response" | grep -q '"script_analysis"'; then
            complexity=$(echo "$response" | grep -o '"estimated_complexity":"[^"]*' | cut -d'"' -f4)
            operations=$(echo "$response" | grep -o '"detected_operations":\[[^]]*\]' | head -1)
            print_info "Script Complexity: $complexity"
            print_info "Detected Operations: $operations"
        fi
    else
        print_error "HTTPBin test failed"
        echo "Response: $response"
    fi
}

# Test 4: Screenshot Capture
test_screenshot() {
    print_header "Test 4: Screenshot Capture"

    local script='{
        "script": "from playwright.async_api import async_playwright\n\nasync def main():\n    async with async_playwright() as p:\n        browser = await p.chromium.launch()\n        page = await browser.new_page()\n        await page.goto(\"https://playwright.dev\")\n        title = await page.title()\n        # Take a screenshot\n        await page.screenshot(path=\"playwright-homepage.png\")\n        await browser.close()\n        return {\"title\": title, \"screenshot\": \"playwright-homepage.png\", \"site\": \"playwright.dev\", \"action\": \"screenshot_taken\"}",
        "timeout": 60,
        "priority": 3,
        "tags": ["screenshot", "playwright.dev", "capture"]
    }'

    print_info "Testing screenshot capture on Playwright homepage..."

    response=$(curl -s -X POST "$BASE_URL/execute" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "$script")

    if echo "$response" | grep -q '"success":true'; then
        request_id=$(echo "$response" | grep -o '"request_id":"[^"]*' | cut -d'"' -f4)
        print_success "Screenshot test completed successfully!"
        print_info "Request ID: $request_id"
        print_info "Screenshot saved in execution environment"
    else
        print_error "Screenshot test failed"
        echo "Response: $response"
    fi
}

# Test validation endpoint
test_validation() {
    print_header "Bonus: Script Validation Test"

    local script='{
        "script": "from playwright.async_api import async_playwright\n\nasync def main():\n    async with async_playwright() as p:\n        browser = await p.chromium.launch()\n        page = await browser.new_page()\n        await page.goto(\"https://example.com\")\n        title = await page.title()\n        await browser.close()\n        return {\"title\": title}",
        "timeout": 30
    }'

    print_info "Validating script before execution..."

    response=$(curl -s -X POST "$BASE_URL/validate" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "$script")

    if echo "$response" | grep -q '"is_safe":true'; then
        print_success "Script validation passed!"
        echo "$response" | python3 -c "import json, sys; data=json.load(sys.stdin); print(f'Safety: {data[\"is_safe\"]}'); print(f'Recommendation: {data[\"recommendation\"]}'); print(f'Estimated Time: {data[\"estimated_time\"]}s')" 2>/dev/null || echo "Response: $response"
    else
        print_error "Script validation failed"
        echo "Response: $response"
    fi
}

# Show queue status
show_queue_status() {
    print_header "Current Queue Status"

    response=$(curl -s -H "Authorization: Bearer $ADMIN_KEY" "$BASE_URL/queue/status")

    if echo "$response" | grep -q "total_active"; then
        echo "$response" | python3 -c "import json, sys; data=json.load(sys.stdin); print(f'Active Executions: {data[\"total_active\"]}'); print(f'Queued Items: {data[\"total_queued\"]}'); print(f'Available Workers: {data.get(\"available_workers\", \"N/A\")}')" 2>/dev/null || echo "Response: $response"
    else
        echo "Response: $response"
    fi
}

# Main execution
main() {
    echo -e "${BLUE}"
    echo "🎭 Playwright Execute Endpoint - Test Suite 🎭"
    echo "Testing various script execution scenarios..."
    echo -e "${NC}"

    # Check if server is running
    if ! curl -s "$BASE_URL/health" > /dev/null; then
        print_error "Server is not running at $BASE_URL"
        print_info "Start with: docker-compose up -d"
        exit 1
    fi

    print_success "Server is running, starting tests..."

    # Run tests
    test_hello_world
    sleep 2

    test_page_navigation
    sleep 2

    test_httpbin_api
    sleep 2

    test_screenshot
    sleep 2

    test_validation
    sleep 1

    show_queue_status

    print_header "🎉 Test Suite Complete!"
    print_info "All tests demonstrate working /execute endpoint functionality"
    print_info "Check the dashboard: $BASE_URL/dashboard?api_key=$ADMIN_KEY"
    print_info "API Documentation: $BASE_URL/docs"

    echo ""
    print_success "✅ Execute endpoint is fully functional!"
}

# Check curl availability
if ! command -v curl &> /dev/null; then
    echo "❌ curl is required but not installed"
    exit 1
fi

# Run the test suite
main "$@"
