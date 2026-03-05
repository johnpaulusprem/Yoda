namespace MediaBot.Configuration;

public class BotOptions
{
    public const string Section = "Bot";
    public string AppId { get; set; } = "";
    public string AppSecret { get; set; } = "";
    public string TenantId { get; set; } = "";
    public string BotBaseUrl { get; set; } = "";
    public string MediaPlatformInstancePublicIp { get; set; } = "";
    public int MediaPlatformInstanceInternalPort { get; set; } = 8445;
    public string? CertificateThumbprint { get; set; }
}
