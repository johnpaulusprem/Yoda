namespace MediaBot.Configuration;

public class SpeechOptions
{
    public const string Section = "Speech";
    public string SubscriptionKey { get; set; } = "";
    public string Region { get; set; } = "eastus";
}
