using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// 准星系统 - 动态准星，根据移动状态、射击状态、开镜状态调整大小
/// </summary>
public class Crosshair : MonoBehaviour
{
    [Header("准星设置")]
    [Tooltip("准星 UI 组件")]
    private Image crosshairImage;
    
    [Header("准星大小参数")]
    [Tooltip("静止时准星大小")]
    public float idleSize = 10f;
    
    [Tooltip("移动时准星大小")]
    public float moveSize = 20f;
    
    [Tooltip("射击时准星大小")]
    public float fireSize = 30f;
    
    [Tooltip("开镜时准星大小")]
    public float scopeSize = 5f;
    
    [Header("过渡设置")]
    [Tooltip("准星大小变化平滑度")]
    public float transitionSpeed = 10f;
    
    private Vector2 currentSize;
    private Vector2 targetSize;
    private bool isMoving;
    private bool isFiring;
    private bool isScoped;
    
    private void Awake()
    {
        crosshairImage = GetComponent<Image>();
        currentSize = new Vector2(idleSize, idleSize);
        targetSize = currentSize;
        UpdateCrosshairSize();
    }
    
    private void Update()
    {
        // 平滑过渡准星大小
        currentSize = Vector2.Lerp(currentSize, targetSize, transitionSpeed * Time.deltaTime);
        UpdateCrosshairSize();
    }
    
    /// <summary>
    /// 设置移动状态
    /// </summary>
    public void SetMoving(bool moving)
    {
        isMoving = moving;
        UpdateTargetSize();
    }
    
    /// <summary>
    /// 设置射击状态
    /// </summary>
    public void SetFiring(bool firing)
    {
        isFiring = firing;
        UpdateTargetSize();
    }
    
    /// <summary>
    /// 设置开镜状态
    /// </summary>
    public void SetScoped(bool scoped)
    {
        isScoped = scoped;
        UpdateTargetSize();
    }
    
    private void UpdateTargetSize()
    {
        if (isScoped)
        {
            targetSize = new Vector2(scopeSize, scopeSize);
        }
        else if (isFiring)
        {
            targetSize = new Vector2(fireSize, fireSize);
        }
        else if (isMoving)
        {
            targetSize = new Vector2(moveSize, moveSize);
        }
        else
        {
            targetSize = new Vector2(idleSize, idleSize);
        }
    }
    
    private void UpdateCrosshairSize()
    {
        if (crosshairImage != null)
        {
            crosshairImage.rectTransform.sizeDelta = currentSize;
        }
    }
    
    /// <summary>
    /// 设置准星颜色（用于不同状态，如受伤时变红）
    /// </summary>
    public void SetColor(Color color)
    {
        if (crosshairImage != null)
        {
            crosshairImage.color = color;
        }
    }
}
