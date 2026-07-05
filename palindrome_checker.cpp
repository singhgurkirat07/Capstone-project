#include <iostream>
#include <string>
#include <algorithm>
#include <cctype>

// Function to check if a string is a palindrome
bool isPalindrome(const std::string& str) {
    // Create a new string to store the preprocessed version
    std::string processedStr;

    // Iterate through the input string
    for (char c : str) {
        // Convert to lowercase and add to processedStr if it's an alphanumeric character
        if (std::isalnum(c)) {
            processedStr += std::tolower(c);
        }
    }

    // Create a reversed version of the processed string
    std::string reversedStr = processedStr;
    std::reverse(reversedStr.begin(), reversedStr.end());

    // Compare the processed string with its reversed version
    return processedStr == reversedStr;
}

int main() {
    // Test cases
    std::cout << "Is 'madam' a palindrome? " << (isPalindrome("madam") ? "Yes" : "No") << std::endl; // Yes
    std::cout << "Is 'A man, a plan, a canal: Panama' a palindrome? " << (isPalindrome("A man, a plan, a canal: Panama") ? "Yes" : "No") << std::endl; // Yes
    std::cout << "Is 'racecar' a palindrome? " << (isPalindrome("racecar") ? "Yes" : "No") << std::endl; // Yes
    std::cout << "Is 'hello' a palindrome? " << (isPalindrome("hello") ? "Yes" : "No") << std::endl; // No
    std::cout << "Is 'No lemon, no melon' a palindrome? " << (isPalindrome("No lemon, no melon") ? "Yes" : "No") << std::endl; // Yes
    std::cout << "Is '12321' a palindrome? " << (isPalindrome("12321") ? "Yes" : "No") << std::endl; // Yes
    std::cout << "Is 'Was it a car or a cat I saw?' a palindrome? " << (isPalindrome("Was it a car or a cat I saw?") ? "Yes" : "No") << std::endl; // Yes

    return 0;
}